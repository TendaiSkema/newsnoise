import sqlite3
import pandas as pd
import json
from logUtils import green, red, yellow, blue, reset
import os



class DBManager:
    def __init__(self):
        path = os.path.dirname(os.path.abspath(__file__))
        conf_path = os.path.join(path, 'config.json')
        db_conf = json.load(open(conf_path))
        self.DB_NAME = db_conf['DB_NAME']
        self.DB_PATH = os.path.join(path, self.DB_NAME)
        self.TABLES = db_conf['TABLES']
        self.TABLE_FIELDS = db_conf['FIELDS']
        self.FIELDS_NAMES = [field['name'] for field in self.TABLE_FIELDS]
        self.VALUES = ', '.join(['?' for _ in self.TABLE_FIELDS])

        #open(self.DB_PATH, 'a').close()
        self.conn = sqlite3.connect(self.DB_PATH)
        if self.conn is None:
            raise Exception(f'{red}Could not connect to database{reset}')
        
        self.conn.execute('pragma foreign_keys = on')
        self.conn.commit()

        self.c = self.conn.cursor()
        self.PRAGMAS = {}
        for table in self.TABLES:
            self.c.execute(f"PRAGMA table_info({self.TABLES[table]})")
            pragmas_raw = self.c.fetchall()
            if len(pragmas_raw) != len(self.TABLE_FIELDS):
                raise Exception(f'Could not get pragmas for table {table}')
            orderd_pragmas = [None for i in range(len(pragmas_raw))]
            for pragma in pragmas_raw:
                orderd_pragmas[pragma[0]] = pragma[1]
            if None in orderd_pragmas:
                raise Exception(f'Could not get pragmas for table {table}')
            self.PRAGMAS[table] = orderd_pragmas

    def __checkIfConnected(func):
        def wrapper(self,*args, **kwargs):
            if self.conn is None:
                raise Exception('Not connected to database')
            return func(self,*args, **kwargs)
        return wrapper

    def pass_filters(self, article_json:dict, newspaper_name:str)->bool:
        if self.check_if_exists(article_json['url'], newspaper_name):
            return False
        if len(article_json['text']) < 1000:
            return False
        if article_json['publication_date'] is None:
            return False
        return True

    @__checkIfConnected
    def insert(self, article_json:dict, newspaper_name:str):
        # check if all fields are present
        for field in self.FIELDS_NAMES:
            if field not in article_json:
                raise Exception(f'Field {field} not in article_json')
        
        if not self.pass_filters(article_json, newspaper_name):
            return False
        
        # Insert article into database
        self.c.execute(f'INSERT INTO {self.TABLES[newspaper_name]} VALUES ({self.VALUES})', 
                       tuple([article_json[field] for field in self.PRAGMAS[newspaper_name]]))

        self.conn.commit()
        return True

    @__checkIfConnected
    def insert_many(self, articles_json:list, newspaper_name:str):
        for article_json in articles_json:
            if self.insert(article_json, newspaper_name):
                print(f'{green}Inserted{reset} {article_json["url"]}')
            else:
                #print(f'{yellow}Rejected{reset} {article_json["url"]}')
                pass

    @__checkIfConnected
    def get_by_publish_date(self, newspaper_name:str, publication_date:str)->pd.DataFrame:
        self.c.execute(f'SELECT * FROM {self.TABLES[newspaper_name]} WHERE publication_date >= ?', (publication_date,))
        articles = self.c.fetchall()
        articles_df = pd.DataFrame(articles, columns=self.PRAGMAS[newspaper_name])
        return articles_df
    
    @__checkIfConnected
    def get_by_WHERE(self, WHERE:str, newspaper_name:str)->pd.DataFrame:
        self.c.execute(f'SELECT * FROM {self.TABLES[newspaper_name]} WHERE {WHERE}')
        articles = self.c.fetchall()
        articles_df = pd.DataFrame(articles, columns=self.PRAGMAS[newspaper_name])
        return articles_df
    
    @__checkIfConnected
    def get_all(self, newspaper_name:str, limit:int=None)->pd.DataFrame:
        if limit is not None:
            self.c.execute(f'SELECT * FROM {self.TABLES[newspaper_name]} LIMIT ?', (limit,))
        else:
            self.c.execute(f'SELECT * FROM {self.TABLES[newspaper_name]}')
        articles = self.c.fetchall()
        articles_df = pd.DataFrame(articles, columns=self.PRAGMAS[newspaper_name])
        return articles_df
    
    @__checkIfConnected
    def check_if_exists(self, url:str, newspaper_name:str):
        self.c.execute(f'SELECT * FROM {self.TABLES[newspaper_name]} WHERE url=?', (url,))
        if self.c.fetchone() is not None:
            return True
        return False

    @__checkIfConnected
    def create_update_tables(self):
        for table in self.TABLES:
            self.c.execute(f'CREATE TABLE IF NOT EXISTS {self.TABLES[table]} ({", ".join([field["name"]+" "+field["type"] for field in self.TABLE_FIELDS])})')
        self.conn.commit()

    def get_all_tables(self):
        self.c.execute('SELECT name FROM sqlite_master WHERE type="table"')
        tables = self.c.fetchall()
        return tables

    @__checkIfConnected
    def get_all_data(self):
        all_data = []
        for table in self.TABLES:
            self.c.execute(f'SELECT * FROM {self.TABLES[table]}')
            all_data += self.c.fetchall()

        articles_df = pd.DataFrame(all_data, columns=self.PRAGMAS[table])
        return articles_df

    @__checkIfConnected
    def update(self, newspaper_name:str, article_json:dict):
        uid = article_json['uid']
        set_str = ','.join([str(x)+'=?' for x in self.FIELDS_NAMES])
        self.c.execute(f'UPDATE {self.TABLES[newspaper_name]} SET {set_str} WHERE uid=?', tuple([article_json[field] for field in self.FIELDS_NAMES]+[uid]))
        self.conn.commit()

    def update_by_fieldname(self, newspaper_name:str, article_json:dict, fieldname:str):
        if fieldname not in self.FIELDS_NAMES:
            raise Exception(f'Fieldname {fieldname} not in {self.FIELDS_NAMES}')
        
        index = article_json[fieldname]
        set_str = ','.join([str(x)+'=?' for x in self.FIELDS_NAMES])
        self.c.execute(f'UPDATE {self.TABLES[newspaper_name]} SET {set_str} WHERE {fieldname}=?', tuple([article_json[field] for field in self.FIELDS_NAMES]+[index]))
        self.conn.commit()

    @__checkIfConnected
    def close(self):
        self.conn.close()