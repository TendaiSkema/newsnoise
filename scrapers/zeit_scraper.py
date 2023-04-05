import requests
from bs4 import BeautifulSoup
import json
from logUtils import warn, info, error, green, blue, orange, reset, grey
from sqlite3 import connect
from datetime import datetime
from sqlite3 import connect
from newspaper import Article
from database.DB_manager import DBManager

START_URL = 'https://www.zeit.de'
CATEGORIES = [
    'wissen',
    'gesellschaft',
    'wirtschaft',
    'gesundheit',
    'wissen',
    'entdecken'
]

def scrape2markdown(article_json):
    title = article_json['title']
    url = article_json['url']
    category = article_json['category']
    abstract = article_json['abstract']
    publication_date = article_json['publication_date']
    article_layout = article_json['article_layout']

    md = f'# {title}\n\n'

    for div in article_layout:
        if div['type'] == 'text':
            md += f'{div["div"]}\n\n'
        elif div['type'] == 'heading':
            md += f'## {div["div"]}\n\n'
        elif div['type'] == 'image':
            img = div['div']
            try:
                md += f"![{img['alt']}]({img['src']})\n"
            except KeyError:
                md += f"![None]({img['src']})\n"

    return {
        'title': title,
        "abstract": abstract,
        'url': url,
        'category': category,
        'author': article_json['author'],
        'text': md,
        'publication_date': article_json['publication_date'],
        'scrape_date': datetime.now().strftime('%Y-%m-%d')                      
    }


def scrape_article(url, category):
    article = Article(url)
    article.download()
    article.parse()

    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')

    main = soup.find('main')

    if article.publish_date is None:
        date_tag = main.find('time')
        if date_tag is None:
            publication_date = datetime.now().strftime('%Y-%m-%d')
        else:
            publication_date = date_tag['datetime'].split('T')[0]
    else:
        publication_date = article.publish_date.strftime('%Y-%m-%d')

    title = main.find('h1').text.replace('\n','')
    abstract = main.find('div', {'class':'summary'}).text
    article_body = main.find('div', {'class':'article-page'})
    siblings = article_body.findChildren(recursive=False)

    article_layout = []
    for sib in siblings:
        if sib.name == 'p':
            article_layout.append({
                    "type": "text",
                    "div": sib.text
                }
            )
        elif sib.name == 'figure':
            image = sib.find('img')
            if image is None:
                continue
            article_layout.append({
                    "type": "image",
                    "div": image
                }
            )
        elif sib.name == 'h2':
            article_layout.append({
                    "type": "heading",
                    "div": sib.text
                }
            )

    article_json = {
        'title': title,
        'url': url,
        'category': category,
        'author': article.authors[0] if len(article.authors) > 0 else None,
        'abstract': abstract,
        'publication_date': publication_date,
        'article_layout': article_layout
    }

    return scrape2markdown(article_json)


def scrape_zeit(db : DBManager):
    articles_json = []
    info('Starting scraping die Zeit.ch')
    for category in CATEGORIES:
        url = f'{START_URL}/{category}'
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')

        main = soup.find('main')
        if main is None:
            raise Exception(f'Error scraping {url}')
        
        all_links = [ a['href'] for a in main.find_all('a')]
        for link in all_links:
            try:
                url = link
                # check if article is already in database
                if db.check_if_exists(url, 'dieZeit'):
                    continue
                elif not "www.zeit.de" in url:
                    continue

                md = scrape_article(url, category)

                articles_json.append(md)

            except Exception as e:
                error(f'Error scraping {url}: {e}')

    return articles_json
