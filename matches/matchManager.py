import json
from logUtils import warn, green, reset, red, yellow, info
from tqdm import tqdm
from datetime import datetime, timedelta
from textUtils import *
from database.DB_manager import DBManager
from textUtils import SummarizManager
from thefuzz import fuzz
from uuid import uuid4
from transformers import GPT2TokenizerFast
tokenizer = GPT2TokenizerFast.from_pretrained('gpt2')
from pandas import DataFrame

from concurrent.futures import ThreadPoolExecutor, as_completed
import os

QUELLEN_STRING = '''
TITEL: {title}
DATE: {publication_date}
ZUSAMMENFASSUNG: {summary}
'''

THREASHHOLD = 0.15

max_found_ratio = 0.0

DB_NAME = 'articles.db'
BLICK_NAME = 'Blick'
TWENTYMIN_NAME = '20min'
TAGI_NAME = 'Tagesanzeiger'

# @GPT: This function compares the similarity of two articles. 
# The articles are provided as dictionaries (`main_art` and `art`), 
# and are formatted into a standard string form using `QUELLEN_STRING`. 
# These formatted strings are then fed to the 'SummarizManager' instance (`summarizer`), 
# which calculates the similarity using a GPT model (presumably, 
# using a method like cosine similarity or some other semantic similarity measure on the vectorized texts). 
# The function returns the similarity score;
def gpt_compare(main_art, art, summarizer: SummarizManager):
    main_source = QUELLEN_STRING.format(**main_art)
    art_summary = QUELLEN_STRING.format(**art)

    return summarizer.GPT_similarity(main_source, art_summary)

def tag_matching(article1:dict, article2:dict) -> float:
    # get all the tags from today and 14days as sets
    set1 = set(article1['tags'])
    set2 = set(article2['tags'])

    # get the ratio between the union and the intersection of the sets
    matching_tags = set1.intersection(set2)
    nr_matching_tags = len(matching_tags)
    union = set1.union(set2)
    score = nr_matching_tags/len(union)

    return score, matching_tags

def compare_articles(articles:DataFrame, date:str):
    sore_map_dict = {}
    articles_today = articles[articles['publication_date'] == date]

    # go over all articles in today
    info(f'Comparing {len(articles_today)} articles from {date}')
    for _,article in tqdm(articles_today.iterrows(), total=len(articles_today)):
        main_art = {}
        # map score to uid
        for _, article2 in articles.iterrows():
            score, matching_tags = tag_matching(article, article2)
            if score > THREASHHOLD:
                main_art[article2['uid']] = score

        sore_map_dict[article['uid']] = main_art
    
    return sore_map_dict

def compress_comparison(data: dict):
    # Create a new dictionary to store the final assignments
    final_dict = {}
    
    # Create an intermediate dictionary to store the highest scores and corresponding main_uids for each sub_uid
    highest_scores = {}
    
    # Iterate over main_uids and their corresponding dictionaries
    info(f'Compressing {len(data)} articles')
    for main_uid, sub_dict in tqdm(data.items(), total=len(data)):
        # Iterate over sub_uids and their scores
        for sub_uid, score in sub_dict.items():
            # If this sub_uid has not been seen before, or if this score is higher than the previous highest score
            if sub_uid not in highest_scores or score > highest_scores[sub_uid][0]:
                # Store this score and main_uid as the highest for this sub_uid
                highest_scores[sub_uid] = (score, main_uid)
    
    # Now that we know the main_uid with the highest score for each sub_uid, we can create the final dictionary
    for sub_uid, (score, main_uid) in tqdm(highest_scores.items(), total=len(highest_scores)):
        # If this main_uid is not yet in the final dictionary, add it with an empty dictionary
        if main_uid not in final_dict:
            final_dict[main_uid] = {}
        # Add this sub_uid and score to the dictionary for this main_uid
        final_dict[main_uid][sub_uid] = score
    
    # Return the final dictionary
    return final_dict

def cleanup_comparison(comp: dict):
    # remove all sub_uids that are the same as the main_uid
    for main_uid, sub_dict in comp.items():
        for sub_uid in list(sub_dict.keys()):
            if sub_uid == main_uid:
                del sub_dict[sub_uid]
    copy_comp = comp.copy()
    # remove all empty sub_uid dictionaries
    for main_uid, sub_dict in copy_comp.items():
        if len(sub_dict) == 0:
            del comp[main_uid]
    return comp



def cross_compare(today_path: str, db: DBManager, summarizer: SummarizManager):
    # read articles from today 
    today = (datetime.today())
    date_14days = (today-timedelta(days=14)).strftime("%Y-%m-%d")
    date_today = (today).strftime("%Y-%m-%d")

    articles = db.get_by_publish_date(None, date_14days)
    articles['tags'] = articles['tags'].apply(lambda x: x.lower().split(';'))

    comparison = compare_articles(articles, date_today)
    comparison = compress_comparison(comparison)
    comparison = cleanup_comparison(comparison)

    # create the match json
    matches = []
    for main_uid, sub_dict in comparison.items():
        main_article = articles[articles['uid'] == main_uid].to_dict('records')[0]
        
        match = {
            'title': None,
            'date': today.strftime("%Y-%m-%d"),
            'summary': None,
            'urls': [main_article['url']],
            'images': get_images(main_article['text']),
            'uid': uuid4().hex,
            'articles': [main_article['uid']],
            'tags': set(main_article['tags']),
            'script': None,
            'input': None,
        }

        for sub_uid, score in sub_dict.items():
            sub_article = articles[articles['uid'] == sub_uid].to_dict('records')[0]

            """ if score < THREASHHOLD*1.5:
                if not gpt_compare(main_article, sub_article, summarizer):
                    continue """

            match['urls'].append(sub_article['url'])
            match['articles'].append(sub_article['uid'])
            match['images'].extend(get_images(sub_article['text']))
            match['tags'] = set(match['tags']).union(set(sub_article['tags']))

        match['tags'] = list(match['tags'])

        if match['images'] == []:
            print(f'{red}Match {match["uid"]} has no images{reset}')
            continue

        matches.append(match)

        # make match sql ready
        match['tags'] = ';'.join(match['tags'])
        match['articles'] = ';'.join(match['articles'])
        match['urls'] = ';'.join(match['urls'])
        for i,image in enumerate(match['images']):
            match['images'][i] = image['url']
        match['images'] = ';'.join(match['images'])

        db.insert(match, 'matches')
        print(f'{green}Match {match["uid"]} created{reset}')

    return matches

# @GPT: This script initiates the DBManager with a predefined DB_NAME, initializes a SummarizManager,
#  then uses the function 'cross_compare' to compare the two. It prints the number of matches found.
#  It is executed if this script is the main entry point (not imported as a module).;
if __name__ == "__main__":
    db = DBManager(DB_NAME)
    summarizer = SummarizManager()
    matches = cross_compare(db, summarizer)
    print(f'{green}Found {len(matches)} matches{reset}')
