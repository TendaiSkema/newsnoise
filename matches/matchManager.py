import json
from logUtils import warn, green, reset, red, yellow, info
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
import random

from textUtils import GPT_PRIMER

DB_NAME = 'articles.db'
BLICK_NAME = 'Blick'
TWENTYMIN_NAME = '20min'
TAGI_NAME = 'Tagesanzeiger'



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


