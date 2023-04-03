import json
from logUtils import warn, green, reset, red, yellow
from tqdm import tqdm
from datetime import datetime, timedelta
from textUtils import *
from database.DB_manager import DBManager
from textUtils import SummarizManager, TTSManager
import requests
from thefuzz import fuzz
from time import sleep
from uuid import uuid4
from transformers import GPT2TokenizerFast
tokenizer = GPT2TokenizerFast.from_pretrained('gpt2')
from PIL import Image

from moviepy.editor import AudioFileClip, ImageClip, concatenate_videoclips
import os
import imgkit

from textUtils import GPT_PRIMER

QUELLEN_STRING = '''
TITEL: {title}
ZEITUNG: {newspaper}
DATE: {publication_date}
ZUSAMMENFASSUNG: {summary}
'''

DB_NAME = 'articles.db'
BLICK_NAME = 'Blick'
TWENTYMIN_NAME = '20min'
TAGI_NAME = 'Tagesanzeiger'

MAX_TOKENS = 4000
MIN_TOKENS = 1500
MAX_IN_TOKENS = MAX_TOKENS-MIN_TOKENS
MIN_OUT_TOKENS = 200

QUELLEN_LENGH = len(tokenizer(QUELLEN_STRING)["input_ids"])
TEMPLATE_LENGH = len(tokenizer(GPT_PRIMER)["input_ids"])



def compare_with_match(match, article, table: str):
    art1_txt = medium_cleanup(article['abstract'])
    art2_txt = medium_cleanup(match['main_article']['article']['abstract'])
    # get ratios
    ratio = fuzz.token_sort_ratio(art1_txt, art2_txt)/100
    set_ratio = fuzz.token_set_ratio(art1_txt, art2_txt)/100
    qratio = fuzz.QRatio(art1_txt, art2_txt)/100
    wratio = fuzz.WRatio(art1_txt, art2_txt)/100
    if ratio < 0.6 and set_ratio < 0.6:
        return None
    
    match['urls'].append(article['url'])
    match['articles'].append({
        'newspaper': table,
        'category': article['category'],
        'article': article,
        'ratios': [ratio, set_ratio, qratio, wratio]
    })
    match['images'].extend(get_images(article['text']))
    
    return match
    
def compare(article1, article2, table1, table2):
    art1_txt = medium_cleanup(article1['abstract'])
    art2_txt = medium_cleanup(article2['abstract'])
    # get ratios
    ratio = fuzz.token_sort_ratio(art1_txt, art2_txt)/100
    set_ratio = fuzz.token_set_ratio(art1_txt, art2_txt)/100
    qratio = fuzz.QRatio(art1_txt, art2_txt)/100
    wratio = fuzz.WRatio(art1_txt, art2_txt)/100
    if ratio < 0.6 and set_ratio < 0.6:
        return None

    return {
        'title': article1['title'],
        'summary': article1['abstract'],
        'urls': [article1['url'], article2['url']],
        'images': get_images(article1['text']),
        'uid': uuid4().hex,
        'articles': [{
            'newspaper': table2,
            'category': article2['category'],
            'article': article2,
            'ratios': [ratio, set_ratio, qratio, wratio]
        }],
        'main_article': {
            'newspaper': table1, 
            'article':article1
        },
    }

def print_founc_matches(matches):
    print(f'Found {len(matches)} matches with {[len(match["articles"]) for match in matches]} articles')
    # print matches
    for m, match in enumerate(matches):
        print("#"*210)
        print("Match NR."+str(m))
        print(f'{green}{match["title"]}{reset}')
        print(f'{red}{match["main_article"]["article"]["url"]}{reset}')
        print("+"*210)
        for i, article_json in enumerate(match['articles']):
            print(f"{yellow}{article_json['newspaper']} | {article_json['article']['title']}{reset}")         
            print('ratio: {0[0]} | set_ratio: {0[1]} | qratio: {0[2]} | wratio: {0[3]}'.format(article_json['ratios']))
            print(f"{yellow}"+210*"_"+f"{reset}")

def cross_compare(db: DBManager, summarizer: SummarizManager):
    date_today = (datetime.today()).strftime("%Y-%m-%d")
    date_14days = (datetime.today()-timedelta(days=14)).strftime("%Y-%m-%d")

    tables = db.TABLES

    compare_data = []
    for table in tables:
        today = db.get_by_publish_date(table, date_today)
        days14 = db.get_by_publish_date(table, date_14days)
        only_14days = days14[~days14['url'].isin(today['url'])]
        compare_data.append({
            'name': table,
            'today': today,
            '14days': days14
        })

    # compare all articles with all articles
    # save matches in a list
    # check if an article is already in the list
    matches = []
    for table1 in compare_data:
        print(f'{yellow}{table1["name"]}{reset}')
        for _, article1_df in tqdm(table1['today'].iterrows(), total=len(table1['today'])):
            article1 = article1_df.to_dict()
            for table2 in compare_data:
                for _, article2_df in table2['14days'].iterrows():
                    article2 = article2_df.to_dict()
                    if article1['url'] == article2['url']:
                        continue
                    # check if both articles are already in the list
                    skip = False
                    already_match = None
                    for i, match in enumerate(matches):
                        if (article1['url'] in match['urls']) and (article2['url'] in match['urls']):
                            skip = True
                            break
                        elif (article1['url'] in match['urls']) or (article2['url'] in match['urls']):
                            already_match = i
                            break
                    # skip if both articles are already in the list
                    if skip:
                        continue

                    if already_match is not None:
                        if article1['url'] not in matches[already_match]['urls']:
                            res = compare_with_match(matches[already_match], article1, table2['name'])
                        else:
                            res = compare_with_match(matches[already_match], article2, table1['name'])

                        if res is not None:
                            matches[already_match] = res
                    else:
                        res = compare(article1, article2, table1['name'], table2['name'])
                        if res is not None:
                            matches.append(res)

    # remove matches with less than 2 articles
    matches = [match for match in matches if len(match['articles']) > 1]

    return matches

def calc_weight(text, nr_articles_in_match=1):
    raw_tokens = len(tokenizer(text)['input_ids'])
    quell_text_tokens = nr_articles_in_match*QUELLEN_LENGH
    relative_max_in = MAX_IN_TOKENS - quell_text_tokens - TEMPLATE_LENGH
    this_rel_max_in = relative_max_in/nr_articles_in_match
    weight = round(this_rel_max_in/raw_tokens,3)
    return weight

def create_input(match, summarizer):
    print(f"{green}{match['title']}{reset}")
    request_str = ""
    for article_json in match['articles']:
        article = article_json['article']
        article['newspaper'] = article_json['newspaper']
        weighted_ratio = calc_weight(article['text'], len(match['articles']))
        if weighted_ratio >= 1:
            article['summary'] = medium_cleanup(article['text'])
        else:
            article['summary'] = summarizer.summarize(article['text'], ratio=weighted_ratio)
        print(f'w: {weighted_ratio} | rT: {len(tokenizer(article["text"])["input_ids"])} | Art NR.: {len(match["articles"])}')
        request_str += QUELLEN_STRING.format(**article)
    print(f'token: {len(tokenizer(request_str)["input_ids"])} chars: {len(request_str)}')

    return request_str

def create_skript(request_str, summarizer, max_retries=5):
    skript = None
    source_name = "api"
    for i in range(max_retries):
        skript, usage = summarizer.get_skript_api(request_str)
        if (usage is None) or (skript is None) or ('completion_tokens' not in usage):
            print(f'{red}Attempt: {i} failed{reset}')
            skript = None
            continue
        elif usage['completion_tokens'] < MIN_OUT_TOKENS:
            print(f'{red}skript too short{reset}: {len(tokenizer(skript)["input_ids"])}')
            skript = None
            continue
        else:
            print(f'{green}skript found{reset}: {len(tokenizer(skript)["input_ids"])}')
            print(f'{green}{len(tokenizer(skript)["input_ids"])}{reset}')
            return skript, source_name
    
    return None, None

def render_html_template(text, image_path=None, template='matches/template.html', css_path='matches/style.css'):
    """
    Renders an HTML template with the given text and image, and saves the resulting image data as a base64-encoded
    PNG file.

    Args:
        text (str): The text to be displayed in the HTML template.
        image_path (str, optional): The path to the image to be used as the background for the HTML template.
            If not provided, a default image will be used.
        template (str, optional): The path to the HTML template file to be used. Defaults to 'template.html'.
    """
    if image_path is None:
        image_path = 'matches/No_Preview_image_2.png'

    image_url_path = 'file:///' + os.path.normpath(os.path.abspath(image_path)).replace('\\', '/')
    # Read the CSS style file
    with open(css_path) as f:
        css = f.read()

    # Read the template HTML file
    with open(template) as f:
        html = f.read()

    # Replace placeholders with actual content
    html = html.replace('{{ css }}', css)
    html = html.replace('{{ text }}', text)
    html = html.replace('{{ image_path }}', image_url_path)

    kitoptions = {
        "enable-local-file-access": None,
        "width": 1920, 
        "height": 1080
    }

    # Render the HTML to a PNG image using imgkit
    imgkit.from_string(html, image_path, options=kitoptions)
    print('Image saved to ' + image_path)

def create_video(image_list, title, base_path, audio_file='audio.mp3', output_file = 'video.mp4'):
    # check if image list is empty
    if len(image_list) == 0:
        image_list = [{'url': 'https://upload.wikimedia.org/wikipedia/commons/1/14/No_Image_Available.jpg', 'txt': 'No Image Available'}]
    
    # download images
    clips = []
    for i, image in enumerate(image_list):
        try:
            url = image['url']
            if '.jpg' in url:
                ending = '.jpg'
            elif '.png' in url:
                ending = '.png'
            elif '.jpeg' in url:
                ending = '.jpeg'
            else:
                raise Exception('Image format not supported: ' + url)
            
            response = requests.get(image['url'])
            with open(f'temp_image{ending}', 'wb') as temp_file:
                temp_file.write(response.content)
                img = Image.open(temp_file.name)
                # resize it to 1080p
                img = img.resize((1920, 1080), Image.ANTIALIAS)
                img.save(temp_file.name)
                if i == 0:
                    render_html_template(title, image_path=temp_file.name)
                clips.append(ImageClip(temp_file.name))
            os.remove(f'temp_image{ending}')
        except Exception as e:
            warn(e)

    # check if no images were downloaded
    if clips == []:
        img = Image.open('matches/No_Preview_image_2.png')
        # resize it to 1080p
        img = img.resize((1920, 1080), Image.ANTIALIAS)
        img.save('temp_image.png')
        render_html_template(title, image_path='temp_image.png')
        clips = [ImageClip('temp_image.png')]
        os.remove(f'temp_image.png')

    # load audio
    audio = AudioFileClip(base_path+audio_file)
    duration_per_image = audio.duration / len(clips)

    # set clip duration according to audio
    for i,_ in enumerate(clips):
        clips[i] = clips[i].set_duration(duration_per_image)

    # create final video
    final_clip = concatenate_videoclips(clips, method='compose')
    final_clip = final_clip.set_audio(audio)
    final_clip.write_videofile(base_path+output_file, fps=24)

    return final_clip

def create_final_video(clips, base_path):
    # TODO: load intro and outro

    final_clip = concatenate_videoclips(clips, method='compose')
    final_clip.write_videofile(base_path+'final.mp4', fps=24)

    return final_clip



def CreateVideo(tts: TTSManager, summarizer: SummarizManager, db: DBManager):
    # create folder for today
    today = datetime.now().strftime('%Y-%m-%dT%H')
    if not os.path.exists("ChatGPT/"+today):
        os.makedirs("ChatGPT/"+today)

    today_path = "ChatGPT/"+today+"/"

    matches = cross_compare(db, summarizer)

    warn(f"Found {len(matches)} matches")
    videos = []
    for match in matches:
        # create folder for match
        if not os.path.exists(f"{today_path}{match['uid']}"):
            os.makedirs(f"{today_path}{match['uid']}")
        with open(f"{today_path}{match['uid']}/match.json", 'w') as f:
            json.dump(match, f, indent=4)

        # create GPT input file
        request_str = create_input(match, summarizer)
        # save input file
        with open(f"{today_path}{match['uid']}/input.txt", 'w', encoding='utf-8') as f:
            f.write(request_str)
        
        # create GPT output file
        skript, source_name = create_skript(request_str, summarizer)
        if skript is None:
            continue

        # add title to skript
        skript = f'{match["title"]}\n\n{skript}'

        with open(f'{today_path}{match["uid"]}/skript_{source_name}.txt', 'w', encoding='utf-8') as f:
            f.write(skript)
        
        tags = summarizer.get_tags_for_skript(skript)

        tts.syntisize(skript, f'{today_path}{match["uid"]}/audio.mp3')
        sleep(10)

        videos.append(create_video(match['images'], match["title"], f'{today_path}{match["uid"]}/'))

    create_final_video(videos, f'{today_path}')

    return today_path, tags


if __name__ == '__main__':
    CreateVideo()

    

