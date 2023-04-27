import json
from logUtils import warn, green, reset, red, yellow, info, blue
from textUtils import *
import requests
from time import sleep
from transformers import GPT2TokenizerFast
tokenizer = GPT2TokenizerFast.from_pretrained('gpt2')
from PIL import Image, ImageDraw, ImageFont
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
    for i in range(max_retries):
        skript_js, usage = summarizer.get_skript_api(request_str)
        skript = skript_js['skript']
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
            return skript_js
    
    return None

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

    # create final video
    info(f"{blue}Creating video for {title}: {base_path}{reset} | t: {audio.duration}")
    final_clip = concatenate_videoclips(clips, method='compose')
    final_clip = final_clip.set_audio(audio)
    final_clip.write_videofile(base_path+output_file, fps=24, threads = 5, logger=None)
    info(f'Video saved to {base_path+output_file}')
    return final_clip

def draw_wrapped_text(draw, text, font, fill, rect, line_spacing=5):
    max_width = rect[2] - rect[0]
    max_height = rect[3] - rect[1]

    # Find the font size that fits the bounding box
    while True:
        # Split the text into words
        words = text.split()

        # Create an empty list to store lines of text
        lines = []
        line = ""

        # Iterate over the words and construct lines
        for word in words:
            test_line = line + " " + word
            test_line_width = draw.textlength(test_line.strip(), font)
            if test_line_width <= max_width:
                line = test_line
            else:
                lines.append(line.strip())
                line = word

        # Add the last line to the list
        if line:
            lines.append(line.strip())

        # Calculate the total height of the text
        total_height = sum([draw.textbbox((0, 0), line, font=font)[3] - draw.textbbox((0, 0), line, font=font)[1] for line in lines]) + (len(lines) - 1) * line_spacing

        # Check if the total height fits the bounding box
        if total_height <= max_height:
            break

        # Decrease the font size
        font_size = font.size - 1
        if font_size <= 0:
            break

        font = ImageFont.truetype(font.path, font_size)

    # Draw each line of text within the bounding box
    y = rect[1] - line_spacing  # Adjust the starting y value
    for line in lines:
        left, top, right, bottom = draw.textbbox((0, 0), line, font=font)
        line_height = bottom - top
        x = rect[0]  # Set the x value to the left bound of the rect
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height + line_spacing

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

def create_final_thumbnail(tags, today_path, title):
    base_image = Image.open('matches/thumbnail.png')
    base_image = base_image.convert('RGBA')

    # Define the bounding box
    bbox = (50, 100, 1000, 650)

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
    response = None
    # download image
    for _ in range(len(images)):
        try:
            response = requests.get(random_front)
        except:
            random_front = random.choice(images)

    if response == None:
        # save base image as thumbnail
        base_image.save(today_path+'final_thumbnail.png')
        return base_image

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

    # add title
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype('matches/Roboto-Bold.ttf', 500)
    draw_wrapped_text(draw, title, font, fill=(255, 255, 255, 255), rect=bbox)

    img.save(today_path+'final_thumbnail.png')

    return img

def create_final_titel(tags, today_path, summatizer):
    all_titles = []
    for match in os.listdir(today_path):
        if os.path.isdir(today_path+match):
            if not os.path.exists(today_path+match+'/skript.json'):
                continue
            with open(today_path+match+'/skript.json') as f:
                data = json.load(f)
                all_titles += data['titel']

    fused_skripts = '\n'.join(all_titles)

    # create title
    title = summatizer.get_title_for_video(fused_skripts)
    if title == '':
        title = None
    
    return title

def process_match(today_path, match, summarizer, tts):
    # create GPT input file
    info(f"Creating input for {match['uid']}")
    request_str = create_input(match, summarizer)
    # save input file
    with open(f"{today_path}{match['uid']}/input.txt", 'w', encoding='utf-8') as f:
        f.write(request_str)
    
    # create GPT output file
    info(f"Creating skript for {match['uid']}")
    skript_js = create_skript(request_str, summarizer)
    if skript_js is None:
        warn(f"{red}Could not create skript for {match['uid']}{reset}")
        return
    
    with open(f'{today_path}{match["uid"]}/skript.json', 'w', encoding='utf-8') as f:
        json.dump(skript_js, f, indent=4)
    
    title = skript_js['titel']

    # update title in match.json
    match['title'] = title
    with open(f"{today_path}{match['uid']}/match.json", 'w') as f:
        json.dump(match, f, indent=4)

    # get tags
    info(f"Getting tags for {match['uid']}")
    tags = summarizer.get_tags_for_skript(skript_js["skript"])
    with open(f'{today_path}{match["uid"]}/tags.json', 'w', encoding='utf-8') as f:
        json.dump(tags, f, indent=4)

    # create audio file
    info(f"Creating audio for {match['uid']}")
    tts.syntisize(skript_js["skript"], f'{today_path}{match["uid"]}/audio.mp3')
    sleep(10)

    info(f"Creating thumbnail for {match['uid']}")
    create_thumbnail(match['images'], tags, f'{today_path}{match["uid"]}/')


