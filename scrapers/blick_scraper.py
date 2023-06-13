import requests
from bs4 import BeautifulSoup
import json
from logUtils import warn, info, error, green, blue, orange, reset, grey
from sqlite3 import connect
from datetime import datetime
from sqlite3 import connect
from newspaper import Article

START_URL = 'https://www.blick.ch'
CATEGORIES = [
    'schweiz',
    'wirtschaft',
    'ausland',
    'politik',
    'meinung',
    'digital',
    'green',
    'life/wissen',
]



def blick_raw2refined(article_json):
    title = article_json['title']
    url = article_json['url']
    category = article_json['category']
    subtitle = article_json['subTitle']
    abstract = article_json['abstract']

    soup = BeautifulSoup(article_json['text'], 'html.parser')
    article_soup = soup.find('article')

    author_soup = article_soup.findChild('a', recursive=False)
    if author_soup is None:
        author = None
    else:
        author_span = author_soup.find('span')
        if author_span is None:
            author = None
        else:
            author = author_span.text

    lineup_raw = article_soup.findChildren(recursive=False)

    lineup = []
    for sib in lineup_raw:
        if sib.name == 'p':
            lineup.append({
                    "type": "text",
                    "div": sib.text
                }
            )
        elif sib.name == 'h3':
            lineup.append({
                    "type": "heading",
                    "div": sib.text
                }
            )
        elif sib.name == 'div':
            images = sib.find_all('img')
            if len(images) > 0:
                imgs = []
                for img in images:
                    pic = img.parent
                    srcs = pic.find_all('source')[0]
                    imgs.append({
                        "src": srcs['srcset'],
                        "alt": img['alt']
                    })

                lineup.append({
                        "type": "images",
                        "images": imgs
                    }
                )
            else:
                lineup.append({
                        "type": "other",
                        "div": sib.prettify()
                    }
                )

    return {
        'title': title,
        'url': url,
        'category': category,
        'subtitle': subtitle,
        'abstract': abstract,
        'author': author,
        'lineup': lineup,
        'publication_date': article_json['publication_date']
    }

def refined2md(article_json):
    title = article_json['title'].replace('\n','')
    url = article_json['url']
    category = article_json['category']
    subtitle = article_json['subtitle'].replace('\n','')
    abstract = article_json['abstract']
    author = article_json['author']
    lineup = article_json['lineup']

    md = f"# {title}\n\n## {subtitle}\n\n{abstract}\n\n"
    for div in lineup:
        if div['type'] == 'text':
            div_txt = div['div'].replace('\n ','')
            md += f"{div['div']}\n\n"
        elif div['type'] == 'heading':
            div_txt = div['div'].replace('\n','')
            md += f"### {div_txt}\n\n"
        elif div['type'] == 'images':
            for img in div['images']:
                src = img['src'].split('1x, ')[0]
                md += f"![{img['alt']}]({src})\n\n"

    return {
        'title': title,
        "abstract": abstract,
        'url': url,
        'category': category,
        'author': author,
        'text': md,
        'publication_date': article_json['publication_date'],
        'scrape_date': datetime.now().strftime('%Y-%m-%d'),
    }

def scrape_article(url, category):

    article = Article(url)
    article.download()
    article.parse()
    if article.publish_date is None:
        publication_date = datetime.now().strftime('%Y-%m-%d')
    else:
        publication_date = article.publish_date.strftime('%Y-%m-%d')

    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')

    main = soup.find('main')

    title_soup = main.find('h2')
    subTitle = title_soup.findAll('div')[0].text
    title = title_soup.findAll('div')[1].text.replace('\n','')

    abstract_soup = title_soup.findNextSibling('div')
    abstract = abstract_soup.text

    if main.find('article') is None:
        return None

    text = main.find('article').prettify()

    article_json = {
        'url': url,
        'category': category,
        'title': title,
        'subTitle': subTitle,
        'abstract': abstract,
        'text': text,
        'publication_date': publication_date
    }

    refined = blick_raw2refined(article_json)
    if refined is None:
        return None
    md = refined2md(refined)
    return md

def scrape_blick(db)-> list:
    articles_json = []
    info('Starting scraping Blick.ch')
    for category in CATEGORIES:
        url = f'{START_URL}/{category}'
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')

        main = soup.find('main')
        all_links = [ a['href'] for a in main.find_all('a')]
        # remove duplicates
        all_links = list(dict.fromkeys(all_links))
        
        for link in all_links:
            try:
                url = f'{START_URL}{link}'
                
                if not url.endswith('.html'):
                    continue
                # check if article is already in database
                if db.check_if_article_exists(url):
                    continue

                md = scrape_article(url, category)
                if md is None:
                    continue
                articles_json.append(md)

            except Exception as e:
                error(f'Error scraping {url}: {e}')

    return articles_json


if __name__ == '__main__':
    DB_NAME = 'articles.db'
    BLICK_NAME = 'blick_articles'

    conn = connect(DB_NAME)
    articles_json = scrape_blick(conn, BLICK_NAME)
    print(len(articles_json))