import requests
from bs4 import BeautifulSoup
import json
from logUtils import warn, info, error, green, blue, orange, reset, grey
from sqlite3 import connect
from datetime import datetime
from newspaper import Article


START_URL = 'https://www.20min.ch'
CATEGORIES = [
    'schweiz',
    'wirtschaft',
    'ausland',
    'wissen',
    'instagram-slider',
    'digital',
    'gesundheit'
    'front',
    'zentralschweiz',
    'e-sport',
    'zuerich',
    'bern',
    'basel',
]

def refine_article(article_json):
    article_soup = BeautifulSoup(article_json['text'], 'html.parser')

    header_data = article_soup.find('header')
    header_json = {}
    if header_data is not None:
        for div in header_data.find_all('div'):
            if 'Title' in div.get('class')[0]:
                header_json['title'] = div.find('h2').text if div.find('h2') is not None else None
            elif 'Author' in div.get('class')[0]:
                header_json['author'] = {}
                header_json['author']['name'] = div.find('dd').text if div.find('dd') is not None else None
                header_json['author']['image'] = div.find('image')['href'] if div.find('image') is not None else None
            elif 'Lead' in div.get('class')[0]:
                header_json['lead'] = div.find('p').text if div.find('p') is not None else None

    if len(header_json.keys()) == 0:
        header_json = None

    article_section = None
    for section in article_soup.findChildren('section'):
        if section.get('class') is None:
            continue
        if 'Article_body' in section.get('class')[0]:
            article_section = section
            break
    if article_section is None:
        error(f'Article {article_json["url"]} has no article section')
        return None

    article_lineup = []
    for div in article_section.findAll('div')[:-1]:
        element_class = div.get('class')[0]
        if 'Ad_' in element_class or 'Poll' in element_class:
            continue
        elif 'Article_element' not in element_class:
            continue
        elif 'Textblockarray' in element_class:
            element_class = 'paragraph'
        elif 'Crosshead' in element_class:
            element_class = 'subheader'
        else:
            element_class = 'other'

        article_lineup.append(
            {
                'class': element_class, 
                'div': div.text if element_class == 'paragraph' or element_class == 'subheader' else div.prettify()
            }
        )
        
    return {
                'title': article_json['title'],
                'publication_date': article_json['publication_date'],
                'abstract': article_json['abstract'],
                'url': article_json['url'],
                'category': article_json['category'],
                'header': header_json,
                'article': article_lineup
            }

def process_other(div):
    text = ''
    soup = BeautifulSoup(div, 'html.parser').findChildren('div', recursive=False)[0]

    if 'Slideshow' in soup.get('class')[0]:
        images = soup.find_all('img')
        if len(images) == 0:
            return ''
        for image in images:
            try:
                text += f"![{image['alt']}]({image['src']})\n"
            except KeyError:
                text += f"![None]({image['src']})\n"
    else:
        pass
    
    return text

def article_refined2md(article):
    # Get the text
    lineup = article['article']

    if article['header'] is None:
        full_text = f"# {article['title']}\n"
    else:
        full_text = f"# {article['header']['title']}\n{article['header']['lead']}\n"

    for line in lineup:
        if line['class'] == 'paragraph':
            full_text += line['div']+'\n'
        elif line['class'] == 'subheader':
            full_text += '\n## '+line['div']+'\n'
        elif line['class'] == 'other':
            full_text += process_other(line['div'])+'\n'
        else:
            pass

    return {
        'title': article['header']['title'] if article['header'] is not None else article['title'],
        'abstract': article['abstract'],
        'text': full_text,
        'author':article['header']['author']['name'] if article['header'] is not None else None,
        'publication_date': article['publication_date'],
        'category': article['category'],
        'url': article['url'],
        'scrape_date': datetime.now().strftime('%Y-%m-%d'),
    }

def scrape_article(article_url, category):
    art_response = requests.get(article_url)
    art_soup = BeautifulSoup(art_response.text, 'html.parser', from_encoding='utf-8')
    full_article = art_soup.find('article')
    if full_article is None:
        return None
    
    try:
        publication_date = full_article.find('time')['datetime']
        publication_date = publication_date.split('T')[0]
    except:
        publication_date = datetime.now().strftime('%Y-%m-%d')
        
    summary = full_article.find('p').text
    article_json = {
        'title': full_article.find('h2').text.replace('\n',''),
        'publication_date': publication_date,
        'abstract': summary,
        'url': article_url,
        'category': category,
        'text': str(full_article)
    }

    article_refined = refine_article(article_json)
    if article_refined is None:
        return None
    article_md = article_refined2md(article_refined)
    
    return article_md

def scrape_20min(db):
    info('Starting scraping 20min.ch')
    articles_json = []
    for category in CATEGORIES:
        url = f'{START_URL}/{category}'
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for article in soup.find_all('article'):
            part_url = article.find('a')['href']

            if '/story/' not in part_url:
                continue

            article_url = START_URL+ part_url

            # check if article is already in database
            if db.check_if_exists(article_url, '20min'):
                continue

            article_md = scrape_article(article_url, category)
            if article_md is None:
                continue
            articles_json.append(article_md)
            print(f"{orange}Articles Scraped {len(articles_json)}{reset}", end='\r')

    return articles_json
          