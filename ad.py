import argparse
import configparser
import hashlib
import os
import shutil

import m3u8
import sqlite3

ad_type = 'ffzy'


def calculate_sha256_from_url(url):
    sha256 = hashlib.sha256()
    with open(url, "rb") as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()


def analyse(url, dir):
    if os.path.exists("content.txt"):
        os.remove("content.txt")
    playlist = m3u8.load(url)
    if playlist.is_variant and len(playlist.playlists) > 0:
        playlist = m3u8.load(playlist.playlists[0].absolute_uri)
    ts_url_dic = []
    for r in playlist.segments:
        ts_url_dic.append(r.absolute_uri)
    with open("content.txt", "w") as file_handle:
        file_handle.write("\n".join(ts_url_dic))
    order = (
            m3u8dl + " -s 8 -x 8 -j 8 --max-concurrent-downloads=16 "
                     "--max-tries=3 --check-certificate=false "
                     "-c --input-file={} --dir={}".format("content.txt", dir)
    )
    os.system(order)
    # for filename in os.listdir(dir):
    #     file_path = os.path.join(dir, filename)
    #     if os.path.isfile(file_path):
    #         sha256 = calculate_sha256_from_url(file_path)
    #         with conn:
    #             conn.execute('''
    #                        INSERT OR REPLACE INTO ads (hash,name)
    #                        VALUES (?,?)''', (sha256, ad_type))


if __name__ == "__main__":
    cf = configparser.ConfigParser()
    cf.read("mydav.ini", encoding="utf-8")
    m3u8dl = cf.get("sys", "m3u8dl")
    ad_sets = set()
    t1_sets = set()
    parser = argparse.ArgumentParser(
        description=''
    )
    parser.add_argument('-u1', help='地址1', default='')
    parser.add_argument('-u2', help='地址2', default='')
    args = parser.parse_args()
    u1 = args.u1
    u2 = args.u2
    if u1 and u1.startswith('http') and u2 and u2.startswith('http'):
        try:
            analyse(url=u1, dir="t1")
            for filename in os.listdir('t1'):
                file_path = os.path.join('t1', filename)
                if os.path.isfile(file_path):
                    t1_sets.add(calculate_sha256_from_url(file_path))
        finally:
            if os.path.exists("t1"):
                shutil.rmtree("t1")

        try:
            analyse(url=u2, dir="t2")
            for filename in os.listdir('t2'):
                file_path = os.path.join('t2', filename)
                if os.path.isfile(file_path):
                    sha256 = calculate_sha256_from_url(file_path)
                    if sha256 in t1_sets:
                        ad_sets.add(sha256)
        finally:
            if os.path.exists("t2"):
                shutil.rmtree("t2")
            os.remove('content.txt')

    if len(ad_sets) > 0:
        print('analyse ad:\n')
        print(ad_sets)
        conn = sqlite3.connect("ad.db")
        with conn:
            for sha256 in ad_sets:
                conn.execute('''
                               INSERT OR REPLACE INTO ads (hash,name)
                               VALUES (?,?)''', (sha256, ad_type))
