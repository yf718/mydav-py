import configparser
import hashlib
import os
import sqlite3
import sys


def calculate_sha256_from_url(url):
    sha256 = hashlib.sha256()
    with open(url, "rb") as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()


def calculate_sha256_for_files(directory, conn):
    if not os.path.exists(directory):
        print(f'file path {directory} not exist')
        return
    for filename in os.listdir(directory):
        file_path = os.path.join(directory, filename)
        clean_file(file_path, conn)


def clean_file(file_path, conn):
    if os.path.exists(file_path):
        sha256 = calculate_sha256_from_url(file_path)
        with conn:
            cursor = conn.execute('''
               select 1 from ads where hash = ?
               ''', (sha256,))
            if cursor.fetchone() is None:
                return
            os.truncate(file_path, 0)
            print('clean file', file_path)
    else:
        print(f"File '{file_path}' does not exist.")


if __name__ == "__main__":
    path = sys.argv[1]
    conn = sqlite3.connect("ad.db")
    cf = configparser.ConfigParser()
    cf.read("mydav.ini", encoding="utf-8")
    root_folder = cf.get('sys', 'root_dir')
    calculate_sha256_for_files(os.path.join(root_folder, 'tmp', path, '1'), conn)
