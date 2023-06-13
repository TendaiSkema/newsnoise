from flask import Flask, request, jsonify
from logUtils import warn, info, error, green, blue, orange, reset,yellow
from scrapers.twentymin_scraper import scrape_20min
from scrapers.blick_scraper import scrape_blick
from scrapers.taggi_scraper import scrape_taggi
from scrapers.zeit_scraper import scrape_zeit
from textUtils import SummarizManager, TTSManager, UploadManager
from database.DB_manager import DBManager
import matches.matchManager as mm
import video.videoManager as vm
import uuid
import multiprocessing as mp
from datetime import datetime

app = Flask(__name__)

BLICK_NAME = 'Blick'
TWENTYMIN_NAME = '20min'
TAGI_NAME = 'Tagesanzeiger'
ZEIT_NAME = 'dieZeit'

@app.route('/is-alive', methods=['GET'])
def is_alive():
    return "Program is running"

@app.route('/scrape/all', methods=['POST'])
def scrape_all():
    # Implement logic here
    pass

@app.route('/scrape/<newspaper_name>', methods=['POST'])
def scrape_newspaper(newspaper_name):
    # Implement logic here
    pass

@app.route('/match', methods=['POST'])
def create_matches():
    # Implement logic here
    pass

@app.route('/video/all', methods=['POST'])
def create_videos_for_all_matches():
    # Implement logic here
    pass

@app.route('/video/<match_uid>', methods=['POST'])
def create_video_for_specific_match(match_uid):
    # Implement logic here
    pass

@app.route('/video/upload', methods=['POST'])
def upload_video():
    # Implement logic here
    pass

if __name__ == '__main__':
    app.run(port=5000, debug=True)
