import json
from logUtils import warn, green, reset, red, yellow, info, blue
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
from moviepy.editor import AudioFileClip, ImageClip, concatenate_videoclips, VideoFileClip

import os
import imgkit
import random

from textUtils import GPT_PRIMER

QUELLEN_STRING = '''
TITEL: {title}
ZEITUNG: {newspaper}
DATE: {publication_date}
ZUSAMMENFASSUNG: {summary}
'''

DESCRIPTION = """Dieses Video wurde automatisch erstellt.
Die Korrektheit der Inhalte kann nicht garantiert werden.

Die Inhalte wurden von den folgenden News-Seiten gesammelt:
- 20min.ch
{20min}
- Blick.ch
{Blick}
- Tagesanzeiger.ch
{Tagesanzeiger}
- Zeit.de
{dieZeit}
"""

MAX_TOKENS = 4000
MIN_TOKENS = 1500
MAX_IN_TOKENS = MAX_TOKENS-MIN_TOKENS
MIN_OUT_TOKENS = 200

QUELLEN_LENGH = len(tokenizer(QUELLEN_STRING)["input_ids"])
TEMPLATE_LENGH = len(tokenizer(GPT_PRIMER)["input_ids"])

locked = False

def calc_weight(text, nr_articles_in_match=1):
    raw_tokens = len(tokenizer(text)['input_ids'])
    quell_text_tokens = nr_articles_in_match*QUELLEN_LENGH
    relative_max_in = MAX_IN_TOKENS - quell_text_tokens - TEMPLATE_LENGH
    this_rel_max_in = relative_max_in/nr_articles_in_match
    weight = round(this_rel_max_in/raw_tokens,3)
    return weight

def create_input(match, summarizer):
    #print(f"{green}{match['title']}{reset}")
    request_str = ""
    for article_json in match['articles']:
        article = article_json['article']
        article['newspaper'] = article_json['newspaper']
        weighted_ratio = calc_weight(article['text'], len(match['articles']))
        if weighted_ratio >= 1:
            article['summary'] = medium_cleanup(article['text'])
        else:
            article['summary'] = summarizer.summarize(article['text'], ratio=weighted_ratio)
        #print(f'w: {weighted_ratio} | rT: {len(tokenizer(article["text"])["input_ids"])} | Art NR.: {len(match["articles"])}')
        request_str += QUELLEN_STRING.format(**article)
    #print(f'token: {len(tokenizer(request_str)["input_ids"])} chars: {len(request_str)}')

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
    info(f'Prepare {len(image_list)} images for video creation')
    if len(image_list) == 0:
        image_list = [{'url': 'https://upload.wikimedia.org/wikipedia/commons/1/14/No_Image_Available.jpg', 'txt': 'No Image Available'}]
    
    # download images
    clips = []
    for i, image in enumerate(image_list):
        try:
            response = requests.get(image['url'])
            temp_img_id = random.randint(0, 1000000000)
            with open(f'temp/temp_image{temp_img_id}.png', 'wb') as temp_file:
                temp_file.write(response.content)
                img = Image.open(temp_file.name)
                # resize it to 1080p
                img = img.resize((1920, 1080), Image.ANTIALIAS)
                img.save(temp_file.name)
                if i == 0:
                    render_html_template(title, image_path=temp_file.name)
                clips.append(ImageClip(temp_file.name))
            os.remove(f'temp/temp_image{temp_img_id}.png')
        except Exception as e:
            warn(e)

    # check if no images were downloaded
    if clips == []:
        img = Image.open('matches/No_Preview_image_2.png')
        # resize it to 1080p
        img = img.resize((1920, 1080), Image.ANTIALIAS)
        img.save('temp/temp_image.png')
        render_html_template(title, image_path='temp/temp_image.png')
        clips = [ImageClip('temp/temp_image.png')]
        os.remove(f'temp/temp_image.png')

    # load audio
    audio = AudioFileClip(base_path+audio_file)
    duration_per_image = audio.duration / len(clips)

    # TODO: add background music

    # set clip duration according to audio
    for i,_ in enumerate(clips):
        clips[i] = clips[i].set_duration(duration_per_image)

    while locked:
        pass
    
    locked = True
    # create final video
    info(f"{blue}Creating video for {title}: {base_path}{reset} | t: {audio.duration}")
    final_clip = concatenate_videoclips(clips, method='compose')
    final_clip = final_clip.set_audio(audio)
    final_clip.write_videofile(base_path+output_file, fps=24, threads = 5, logger=None)
    info(f'Video saved to {base_path+output_file}')
    locked = False
    return final_clip

def create_final_video(clips, base_path):
    intro = VideoFileClip('video/intro.mp4')
    transition = VideoFileClip('video/transition.mp4')
    all_clips = [intro]
    for clip in clips:
        all_clips.append(clip)
        all_clips.append(transition)
    
    # remove last transition
    all_clips = all_clips[:-1]

    # create final video
    final_clip = concatenate_videoclips(all_clips, method='compose')
    final_clip.write_videofile(base_path+'final.mp4', fps=24, threads = 1000)

    return final_clip

def create_thumbnail(images, tags, today_path):
    base_image = Image.open('matches/thumbnail.png')
    base_image = base_image.convert('RGBA')

    if images == []:
        base_image.save(today_path+'thumbnail.png')
        return base_image

    random_front = random.choice(images)

    # download image
    found = False
    for i in range(100):
        try:
            response = requests.get(random_front['url'])
            found = True
        except:
            random_front = random.choice(images)
        
        if found:
            break
    
    if not found:
        random_front = {'url': 'https://upload.wikimedia.org/wikipedia/commons/1/14/No_Image_Available.jpg', 'txt': 'No Image Available'}
        response = requests.get(random_front['url'])

    temp_image_id = random.randint(0, 100000)
    with open(f'temp/temp_image{temp_image_id}.png', 'wb') as temp_file:
        temp_file.write(response.content)
        img = Image.open(temp_file.name)

    # remove temp file
    try:
        os.remove(f'temp/temp_image{temp_image_id}.png')
    except:
        warn('Could not remove temp file!!')
    
    img = img.resize(base_image.size)
    img = img.convert('RGBA')

    # create thumbnail
    img.paste(base_image, (0, 0), base_image)
    img.save(today_path+'thumbnail.png')

    return img

def create_final_thumbnail(tags, today_path):
    base_image = Image.open('matches/thumbnail.png')
    base_image = base_image.convert('RGBA')

    # load all natches from today and get all image links
    images = []
    for match in os.listdir(today_path):
        if os.path.isdir(today_path+match):
            with open(today_path+match+'/match.json') as f:
                data = json.load(f)
                images += [img_dic['url'] for img_dic in data['images']]

    if images == []:
        # save base image as thumbnail
        base_image.save(today_path+'final_thumbnail.png')
        return base_image
    # get random image
    random_front = random.choice(images)
    # download image
    response = requests.get(random_front)
    temp_image_id = random.randint(0, 100000)
    with open(f'temp/temp_image{temp_image_id}.jpg', 'wb') as temp_file:
        temp_file.write(response.content)
        img = Image.open(temp_file.name)

    # remove temp file
    try:
        os.remove(f'temp/temp_image{temp_image_id}.jpg')
    except:
        warn('Could not remove temp file!!')
    
    img = img.resize(base_image.size)
    img = img.convert('RGBA')

    # create thumbnail
    img.paste(base_image, (0, 0), base_image)
    img.save(today_path+'final_thumbnail.png')

    return img

def process_match(today_path, match, summarizer, tts):
    # create folder for match
    if not os.path.exists(f"{today_path}{match['uid']}"):
        os.makedirs(f"{today_path}{match['uid']}")
    with open(f"{today_path}{match['uid']}/match.json", 'w') as f:
        json.dump(match, f, indent=4)

    # create GPT input file
    info(f"Creating input for {match['uid']}")
    request_str = create_input(match, summarizer)
    # save input file
    with open(f"{today_path}{match['uid']}/input.txt", 'w', encoding='utf-8') as f:
        f.write(request_str)
    
    # create GPT output file
    info(f"Creating skript for {match['uid']}")
    skript, source_name = create_skript(request_str, summarizer)
    if skript is None:
        warn(f"{red}Could not create skript for {match['uid']}{reset}")
        return
    
    with open(f'{today_path}{match["uid"]}/skript_{source_name}.txt', 'w', encoding='utf-8') as f:
        f.write(skript)
    
    title = skript.split('\n')[0]

    # update title in match.json
    match['title'] = title
    with open(f"{today_path}{match['uid']}/match.json", 'w') as f:
        json.dump(match, f, indent=4)

    # get tags
    info(f"Getting tags for {match['uid']}")
    tags = summarizer.get_tags_for_skript(skript)
    with open(f'{today_path}{match["uid"]}/tags.json', 'w', encoding='utf-8') as f:
        json.dump(tags, f, indent=4)

    # create audio file
    info(f"Creating audio for {match['uid']}")
    tts.syntisize(skript, f'{today_path}{match["uid"]}/audio.mp3')
    sleep(10)

    info(f"Creating thumbnail for {match['uid']}")
    create_thumbnail(match['images'], tags, f'{today_path}{match["uid"]}/')


