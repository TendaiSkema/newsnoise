from summarizer import TransformerSummarizer
import google_auth_oauthlib.flow
import googleapiclient.discovery
import googleapiclient.errors
import os
import openai
import azure.cognitiveservices.speech as speechsdk
from time import time, sleep
from random import choice
from secrets.secrets import AZURE_KEY, AZURE_REGION, OPENAI_KEY, GOOGLE_APPLICATION_CREDENTIALS

openai.api_key = OPENAI_KEY
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = GOOGLE_APPLICATION_CREDENTIALS

ALLOWED_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZäöüÄÖÜß .,;:!?-&()[]{}#\""

GPT_PRIMER = """
Schreibe ein Transkript für eine Potcast, dass von einem TTS gesprochen wird, aus den Quellen welche ich dir geben werde.
Mindestens 100 Wörter plus a title.

jede Quelle besteht aus:
TITEL: Überschrift des Artikels
ZEITUNG: Welche zeitung der Artikel veröffentlicht hat
DATE: Datum wann der Artikel veröffentlicht wurde
ZUSAMMENFASSUNG: Zusammenfassung des vollen Artikels

Beispiel:
quellen (input):

TITEL: News2Noise tested  AI generated News
ZEITUNG: Tagesanzeiger
DATE: 2023-01-01
ZUSAMMENFASSUNG: Heute hat die Firma News2Noise den ersten Artikel automatisch generiert. Chat GPT hat dabei eine wichtige rolle übernommen. ob sich das lohn wirt sich zeigen.

TITEL: News2Noise Erfolgs Schlager
ZEITUNG: 20min
DATE: 2023-01-14
ZUSAMMENFASSUNG: News2Noise hat die News Szene revolutioniert. Jeder hört nun den Potcast.

Transkript (output):
News2Noise Erfolgs Schlager

Wie der Tagesanzeiger vor 2 Wochen berichtete hat News2Noise eine neue form der News Generierung getestet. 
Nun berichtet 20min das dieses Konzept ein Erfolgs Schlager ist.

Antworte mit ACK wenn du verstehst.
"""

GPT_SIMILARITY_PRIMER = '''Ich gebe dir einen Haupt-Artikel. darauf folgend gebe ich dir weitere Artikel. Du antwortest nur mit ACK oder NACK.
Antworte mit ACK wenn der gegebene Artikel über das selbe Thema ist wie der Haupt-Artikel.
ansonsten NACK.
Achte darauf das z.B. die selben personen oder ort etc. darin vorkommen.

hier der Haupt-Artikel:
{text}
'''

class TTSManager:
    def __init__(self) -> None:
        self.speech_config = speechsdk.SpeechConfig(subscription=AZURE_KEY, region=AZURE_REGION)
        self.voices = [
            'de-AT-JonasNeural',
            'de-DE-RalfNeural',
            #"de-CH-LeniNeural",
            "de-AT-IngridNeural",
            "de-DE-ElkeNeural"
        ]

    def syntisize(self, text, path):
        self.speech_config.speech_synthesis_voice_name = choice(self.voices)
        audio_config = speechsdk.audio.AudioOutputConfig(filename=path)
        speech_synthesizer = speechsdk.SpeechSynthesizer(speech_config=self.speech_config, audio_config=audio_config)
        speech_synthesis_result = speech_synthesizer.speak_text_async(text).get()
        if speech_synthesis_result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
            print(f"Speech synthesis Failed: {speech_synthesis_result.reason} .")
            return

class UploadManager:
    def __init__(self) -> None:
        # Set up the YouTube API client
        scopes = ["https://www.googleapis.com/auth/youtube.upload"]
        flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
            "secrets/client_secret_676651930909-75fbsv918hglgedf7776vua3v5rq1ldr.apps.googleusercontent.com.json", scopes)
        self.credentials = flow.run_console()
        self.youtube = googleapiclient.discovery.build("youtube", "v3", credentials=self.credentials)

    def upload(self, video_path, title, description, tags, category_id):
        # Upload the video
        request_body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": category_id,
                'defaultLanguage': 'de'
            },
            "status": {
                "privacyStatus": "private",  # Change to "public" or "private" as desired
                'madeForKids': False
            }
        }
        
        if os.path.exists(video_path):
            insert_request = self.youtube.videos().insert(
                part=",".join(request_body.keys()),
                body=request_body,
                media_body=googleapiclient.http.MediaFileUpload(video_path)
            )
            response = insert_request.execute()
            print(f"Video uploaded successfully. Video ID: {response['id']}")
        else:
            print(f"Video file not found: {video_path}")

        return response['id']

    def set_thumbnail(self, video_id, thumbnail_path):
        try:
            request = self.youtube.thumbnails().set(
                videoId=video_id,
                media_body=googleapiclient.http.MediaFileUpload(thumbnail_path)
            )
            response = request.execute()
            print(f"Thumbnail uploaded successfully. Response: {response['kind']}")
            return True
        except Exception as e:
            print(f"Thumbnail upload failed. Error: {e}")
            return False

class SummarizManager:
    def __init__(self) -> None:
        self.GPT2_model = TransformerSummarizer(transformer_type="GPT2",transformer_model_key="gpt2-medium")

    def summarize(self, text, ratio=0.33):
        text = medium_cleanup(text)
        return ''.join(self.GPT2_model(text, ratio=ratio))

    def GPT_similarity(self, mainText, text) -> bool:
        primer = GPT_SIMILARITY_PRIMER.format(text=mainText)
        for _ in range(5):
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                        {"role": "user", "content": primer},
                        {"role": "assistant", "content": "ACK"},
                        {"role": "user", "content": text}
                    ]
            )
            answer = response['choices'][0]['message']['content'] 
            if answer == 'ACK':
                return True
            elif answer == 'NACK':
                return False
            
            print(f"Bad Answer: {response['choices'][0]['message']['content']}")

        print("GPT Similarity failed")
        return False


    def get_skript_api(self, text: str, retries: int = 5)->str:
        for _ in range(retries): 
            try:
                # Note: you need to be using OpenAI Python v0.27.0 for the code below to work
                response = openai.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    messages=[
                            {"role": "user", "content": GPT_PRIMER},
                            {"role": "assistant", "content": "ACK"},
                            {"role": "user", "content": text}
                        ]
                    )
                return response['choices'][0]['message']['content'], response['usage']
            except Exception as e:
                print(e)
            sleep(5)
        
        return None, None

    def get_tags_for_skript(self, text: str, retries: int = 5)->list:
        sys_template = """
            Erstelle eine Tag liste mit maximal 3 Tags im format:
            tag1,tag2,tag3,

            für das folgende Transkript eines Youtube Videos:
        """
        for _ in range(retries): 
            try:
                # Note: you need to be using OpenAI Python v0.27.0 for the code below to work
                response = openai.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    messages=[
                            {"role": "system", "content": """Du bist ein helfender Assistent."""},
                            {"role": "user", "content": sys_template+text}
                        ]
                    )
                tags = response['choices'][0]['message']['content'].split(',')
                return tags
            except Exception as e:
                print(e)
            sleep(5)
        
        return []

    def get_thumbnail_description(self, text: str, retries: int = 5)->str:
        sys_template = """Erstelle eine Beschreibung für das folgende Transkript eines Youtube Videos mit den Themen:\n"""
        for _ in range(retries): 
            try:
                # Note: you need to be using OpenAI Python v0.27.0 for the code below to work
                response = openai.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    messages=[
                            {"role": "system", "content": """Du bist ein helfender Assistent."""},
                            {"role": "user", "content": sys_template+text}
                        ]
                    )
                return response['choices'][0]['message']['content']
            except Exception as e:
                print(e)
            sleep(5)
        
        return None

def remove_special_chars(text: str) -> str:
    return ''.join([char for char in text if char in ALLOWED_CHARS])

def remove_stop_words(text: str) -> str:
    split_text = text.split(' ')
    split_text = [word for word in split_text if word not in UNNECESSARY_WORDS]
    return ' '.join(split_text)

# removes all images from the text
def remove_images(text: str) -> str:
    split_text = text.split('\n')
    # remove all lines with images
    image_less_text = []
    for line in split_text:
        if '![' in line:
            continue
        image_less_text.append(line)
    text = '\n'.join(image_less_text)
    while '  ' in text:
        text = text.replace('  ', ' ')
    return text

def cleanup_for_doc2vec(text: str) -> str:
    text = remove_special_chars(text)
    split_text = text.split('\n')
    #remove all empty lines
    split_text = [line for line in split_text if line != '']
    # remove all lines with images
    image_less_text = []
    for line in split_text:
        if '![' in line:
            continue
        image_less_text.append(line)
    text = '\n'.join(image_less_text)
    text = text.replace('#', '')
    text = text.replace(',', ' , ')
    text = text.replace('.', ' . ')
    text = text.replace('?', ' ? ')
    text = text.replace('!', ' ! ')
    while '  ' in text:
        text = text.replace('  ', ' ')
    return text

def cleanup(text:str)->str:
    text = remove_special_chars(text)
    text = remove_stop_words(text)
    split_text = text.split('\n')
    #remove all empty lines
    split_text = [line for line in split_text if line != '']
    # remove all lines with images
    image_less_text = []
    for line in split_text:
        if '![' in line:
            continue
        image_less_text.append(line)
    text = '\n'.join(image_less_text)
    text = text.replace('#', '')
    while '  ' in text:
        text = text.replace('  ', ' ')
    return text

def soft_cleanup(text: str) -> str:
    text = remove_special_chars(text)
    split_text = text.split('\n')
    soft_cleand_text = []
    #remove all empty lines
    for i, line in enumerate(split_text[:-1]):
        if line == '' and split_text[i+1] == '':
            continue
        soft_cleand_text.append(line)

    text = '\n'.join(soft_cleand_text)
    return text

def medium_cleanup(text: str)->str:
    text = remove_images(text)
    text = [line for line in text.split('\n') if (line != '') or ('# ' in line)]
    return '\n'.join(text)

def get_images(text: str) -> list:
    split_text = text.split('\n')
    images = []
    for line in split_text:
        if '![' in line:
            images.append(line)
    
    imag_map = []
    for image in images:
        # get text from [...]
        image_text = image[image.find('[')+1:image.find(']')]
        # get image url from (...)
        image_url = image[image.find('(')+1:image.find(')')]
        imag_map.append({'txt':image_text, 'url':image_url})
    return imag_map
