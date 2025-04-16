import configparser
import hashlib
import os
import shutil
import sys

import m3u8
import sqlite3

ad_type = 'ffzy'


def calculate_sha256_from_url(url):
    sha256 = hashlib.sha256()
    with open(url, "rb") as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()


def analyse(url, dir, conn):
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
    for filename in os.listdir(dir):
        file_path = os.path.join(dir, filename)
        if os.path.isfile(file_path):
            sha256 = calculate_sha256_from_url(file_path)
            with conn:
                conn.execute('''
                           INSERT OR REPLACE INTO ads (hash,name)
                           VALUES (?,?)''', (sha256, ad_type))


if __name__ == "__main__":
    cf = configparser.ConfigParser()
    cf.read("mydav.ini", encoding="utf-8")
    m3u8dl = cf.get("sys", "m3u8dl")
    if sys.argv[1] and sys.argv[1].startswith('http'):
        conn = sqlite3.connect("ad.db")
        with conn:
            conn.execute("delete from ads where name = ?", (ad_type,))
            analyse(url=sys.argv[1], dir="tmp", conn=conn)
            shutil.rmtree("tmp")
