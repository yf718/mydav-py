import argparse
import base64
import configparser
import logging
import os
import platform
import re
import subprocess
import sys
import time
import json

import m3u8
import requests
from urllib.parse import urljoin

# DEFAULT_PROXY_URL = 'http://127.0.0.1:8088'
# hls_proxy_url = os.environ.get('HLS_PROXY_URL', DEFAULT_PROXY_URL)
is_windows = platform.system() == "Windows"
ad_file_name = "ad.sh"
if is_windows:
    ad_file_name = "ad.bat"
current_path = os.path.dirname(os.path.abspath(__file__))
if getattr(sys, 'frozen', False):
    current_path = os.path.dirname(sys.executable)
ad_file = "--on-download-complete {}".format(os.path.join(current_path, ad_file_name))
max_concurrent_downloads = 16
max_tries = 3

cf = configparser.ConfigParser()
cf.read("mydav.ini", encoding="utf-8")
m3u8dl = cf.get('sys', 'm3u8dl')

hls_proxy_url = ''
if 'hls_proxy_url' in cf.options('sys'):
    hls_proxy_url = cf.get('sys', 'hls_proxy_url')
if hls_proxy_url == '':
    hls_proxy_url = 'http://127.0.0.1:{}'.format(cf.get('sys', 'port'))

my_logger = logging.getLogger()
my_logger.setLevel(logging.INFO)
fileHandler = logging.FileHandler('downserver.log', mode='a', encoding='UTF-8')
fileHandler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
fileHandler.setFormatter(formatter)
my_logger.addHandler(fileHandler)

headers = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,"
              "application/signed-exchange;v=b3;q=0.9",
    "Connection": "Keep-Alive",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/85.0.4183.102 Safari/537.36 "
}


def remove_ad2(base_url: str):
    if cf.has_section('ad_hash'):
        for _, v in cf.items('ad_hash'):
            if re.search(v, base_url):
                return ad_file
    return ""


def remove_ad1(base_url: str, segments: m3u8.SegmentList) -> int:
    del_index = get_ad_index(base_url, segments)
    my_logger.info("del size: {}".format(len(del_index)))
    for index in sorted(del_index, reverse=True):
        if 0 <= index < len(segments):
            segments.pop(index)
    return len(del_index)


def remove_ad(base_url: str, segments: m3u8.SegmentList):
    # ad_num = remove_ad1(base_url, segments)
    # if ad_num == 0:
    #     return remove_ad2(base_url)
    # return ''
    return remove_ad2(base_url)


def get_ad_index(base_url: str, segments: m3u8.SegmentList) -> []:
    if 'ffzy' in base_url:
        return ffzy_ad_idx(segments)
    elif re.search(r'lz-?cdn', base_url) or re.search(r'cdn-?lz', base_url):
        return ffzy_ad_idx(segments)
    elif 'kuaikan' in base_url:
        return kuaikan_ad_idx(segments)
    elif 'suonizy' in base_url:
        return kuaikan_ad_idx(segments)
    return []


def ffzy_ad_idx(segments: m3u8.SegmentList) -> []:
    file_name, _ = os.path.splitext(segments[0].uri)
    del_index = []
    zero_size = len(str(len(segments)))
    zeros_string = '0' * zero_size
    if file_name.endswith(zeros_string):
        a = file_name[0:-zero_size]
        for i, segment in enumerate(segments):
            if a not in segment.uri:
                del_index.append(i)
    return del_index


def file_hash_del_ad(segments: m3u8.SegmentList) -> int:
    del_index = []
    for i, segment in enumerate(segments):
        ad_path = str(segment.uri).split("&index=")[1] + ".ad"
        if os.path.exists(ad_path):
            del_index.append(i)
    my_logger.info("file hash del ad, size: {}".format(len(del_index)))
    for index in sorted(del_index, reverse=True):
        if 0 <= index < len(segments):
            segments.pop(index)
    return len(del_index)


def kuaikan_ad_idx(segments: m3u8.SegmentList) -> []:
    del_index = []
    path_obj = {}
    for segment in segments:
        segment_url = segment.uri
        path = segment_url[:segment_url.rfind("/")]
        if path in path_obj:
            path_obj[path] = path_obj[path] + 1
        else:
            path_obj[path] = 1
    if len(path_obj.keys()) >= 2:
        max_key = max(path_obj, key=path_obj.get)
        my_logger.info("kuaikan_ad_idx max key: {}".format(max_key))
        for i, segment in enumerate(segments):
            if max_key not in segment.uri:
                del_index.append(i)
    return del_index


class RequestsClient:
    def __init__(self, headers, timeout=None):
        self._headers = headers
        self._timeout = timeout
    def download(self, uri, timeout=None, headers={}, verify_ssl=True):
        # xmflv
        if '122.228.8.29:4433' in uri:
            headers['origin'] = "https://jx.xmflv.com"
        o = requests.get(uri, timeout=self._timeout, headers=self._headers, verify=False, allow_redirects=True)
        return o.text, urljoin(o.url, ".")


def down_load(url: str, tmp_idr: str, m3u8_file_path: str):
    if os.path.exists(tmp_idr) or os.path.exists(m3u8_file_path):
        return
    other_command = ""
    if '122.228.8.29:4433' in url:
        other_command += '--header="origin: https://jx.xmflv.com"'
    playlist = m3u8.load(url, http_client=RequestsClient(headers=headers))
    if playlist.is_variant and len(playlist.playlists) > 0:
        playlist = m3u8.load(playlist.playlists[0].absolute_uri, http_client=RequestsClient(headers=headers))

    key_dic = {}
    for r in playlist.keys:
        if r is not None:
            r.uri = get_key(r.absolute_uri, key_dic)
    ad_command = remove_ad(url, playlist.segments)
    ts_url_dic = {}
    if len(playlist.segments) > 0:
        for index, r in enumerate(playlist.segments):
            if r.key is not None:
                r.key.uri = get_key(r.key.absolute_uri, key_dic)
            segment_name = '{:08d}.ts'.format(index)
            ts_url_dic[segment_name] = get_input_file_item(r.absolute_uri, segment_name)
            r.uri = '{}/m3u8?url={}&index={}'.format(hls_proxy_url, r.absolute_uri,
                                                     os.path.join(tmp_idr, "1", segment_name))
        playlist.dump(m3u8_file_path)
        if not os.path.exists(m3u8_file_path):
            my_logger.info("error: get m3u8 content error!!, url:" + url + ",m3u8_file_path:" + m3u8_file_path)
            return
        # if hls_proxy_url == DEFAULT_PROXY_URL:
        #     for line in fileinput.input(m3u8_file_path, inplace=True):
        #         print(line.replace(DEFAULT_PROXY_URL, ''), end='')
        os.makedirs(tmp_idr, exist_ok=True)
        temp_file = os.path.join(tmp_idr, 'content.txt')
        with open(temp_file, 'w') as file_handle:
            file_handle.write('\n'.join(ts_url_dic.values()))
        my_logger.info("{}:start down,total files:{}".format(tmp_idr, len(ts_url_dic)))
        down_count_list = []
        while True:
            down_count_list.append(exec_down(temp_file, tmp_idr, ad_command, other_command))
            if not os.path.exists(temp_file):
                my_logger.info("{}:download finished".format(tmp_idr))
                break
            retry_times = len(down_count_list)
            if retry_times > 2 and down_count_list[retry_times - 1] == 0 and down_count_list[retry_times - 2] == 0:
                my_logger.error("down error: {}".format(temp_file))
                break
            time.sleep(1)

        if ad_command != "":
            if file_hash_del_ad(playlist.segments) > 0:
                playlist.dump(m3u8_file_path)


def get_input_file_item(absolute_uri, segment_name):
    input_file = "{}\n out={}".format(absolute_uri, segment_name)
    # xmflv
    # if 'tz.m3u8.pw' in absolute_uri or '122.228.8.29:4433' in absolute_uri:
    #     input_file += '\n header=origin: https://jx.xmflv.com'
    return input_file


def exec_down(temp_file, tmp_idr, ad_command, other_command):
    down_load_file_dir = os.path.join(tmp_idr, "1")
    order = '{} -s 8 -x 8 -j 8 --max-concurrent-downloads={} ' \
            '--max-tries={} --check-certificate=false ' \
            '-c --input-file={} --dir={}'.format(m3u8dl, max_concurrent_downloads, max_tries, temp_file,
                                                 down_load_file_dir)
    if ad_command != "":
        order = order + " " + ad_command
    if other_command != "":
        order = order + " " + other_command
    exc_order(order)
    if not os.path.exists(temp_file):
        logging.error("{} error del!!".format(temp_file))
        return
    new_lines = []
    with open(temp_file, 'r') as file:
        lines = file.readlines()
    total_count = 0
    down_count = 0
    for line in lines:
        if line.startswith("http"):
            new_lines.append(line.rstrip())
            total_count = total_count + 1
        elif line.strip().startswith("out="):
            out_path = line.strip().split("=")[1].strip()
            if os.path.exists(os.path.join(down_load_file_dir, out_path)) and not os.path.exists(
                    os.path.join(down_load_file_dir, out_path + ".aria2")):
                down_count = down_count + 1
                new_lines.pop()
            else:
                new_lines.append(line.rstrip())
    my_logger.info('{} download, total:{} download count:{}'.format(tmp_idr, total_count, down_count))
    # 下载完成
    if len(new_lines) == 0:
        os.remove(temp_file)
    else:
        if down_count == 0:
            return down_count
        with open(temp_file, 'w') as file:
            file.write("\n".join(new_lines))
    return down_count


def kill_down(tmp_dir):
    try:
        os.remove(os.path.join(tmp_dir, "content.txt"))
    except Exception as e:
        logging.error(e)
    # 创建一个文件
    with open(os.path.join(tmp_dir, "del.lock"), 'w') as file:
        pass
    if is_windows:
        exc_order("taskkill /F /IM aria2c.exe")
    else:
        exc_order("pkill -9 -f {}".format(os.path.basename(tmp_dir)))


def get_key(key_url, key_dic):
    if key_url is None:
        return key_url
    if key_url.startswith(hls_proxy_url):
        return key_url
    if key_url in key_dic:
        return key_dic[key_url]
    try:
        if key_url.startswith("http"):
            res = requests.get(key_url, headers=headers, timeout=20, allow_redirects=True, verify=False)
            logging.info("start get key : " + key_url)
            if res.status_code == 200:
                key_dic[key_url] = base64.urlsafe_b64encode(res.content).decode()
                my_logger.info("get key success, url={},key={}".format(key_url, key_dic[key_url]))
                return '{}/ext-x-key?key={}'.format(hls_proxy_url, key_dic[key_url])
    except Exception as e:
        logging.error('get key error,key url={}, err={}'.format(key_url, e))
    return key_url


def other_down(url, down_load_file_dir):
    order = '{} -s 8 -x 8 -j 8 --max-concurrent-downloads={} ' \
            '--max-tries={} --check-certificate=false ' \
            '--dir={} "{}"'.format(m3u8dl, max_concurrent_downloads, max_tries, down_load_file_dir, url)
    my_logger.info(order)
    exc_order(order)


def exc_order(order):
    my_logger.info(order)
    if is_windows:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        subprocess.call(order, startupinfo=si)
    else:
        os.system(order)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description=''
    )

    parser.add_argument('-u', help='地址', default='')
    parser.add_argument('-H', help='请求头', default='')
    parser.add_argument('-t', help='缓存文件路径', default='')
    parser.add_argument('-M', help='m3u8文件地址', default='')
    parser.add_argument('-c', help='context文件路径', default='')

    group = parser.add_mutually_exclusive_group()
    group.add_argument('--other', action='store_true', help='快速模式')
    group.add_argument('--kill', action='store_true', help='慢速模式')

    args = parser.parse_args()
    my_logger.info("{}".format(args))

    tmp_dir = args.t
    url = args.u
    if url:
        url = url.strip('"')
    m3u8_file_path = args.M
    content_path = args.c
    if args.H:
        try:
            heads = json.loads(args.H)
            if heads:
                for k, v in heads.items():
                    headers[k] = v
        except Exception as e:
            my_logger.error(e)

    if args.kill:
        kill_down(tmp_dir)
    elif args.other:
        other_down(url, tmp_dir)
    elif content_path:
        if content_path.endswith('content.txt') and os.path.exists(content_path):
            exec_res = exec_down(content_path, os.path.dirname(content_path), "", "")
            print("down count ", exec_res)
        else:
            print("{} is not content.txt".format(content_path))
    else:
        if url and tmp_dir and m3u8_file_path:
            down_load(url, tmp_dir, m3u8_file_path)

    # if len(sys.argv) >= 4:
    #     my_logger.info("python down_aria2.py \"{}\"".format("\" \"".join(sys.argv[1:])))
    #     if sys.argv[4] != "":
    #         try:
    #             heads = json.loads(sys.argv[4])
    #             if heads:
    #                 for k, v in heads.items():
    #                     headers[k] = v
    #         except Exception as e:
    #             my_logger.error(e)
    #     down_load(sys.argv[2].strip('"'), sys.argv[1], sys.argv[3])
    # elif len(sys.argv) == 3:
    #     other_down(sys.argv[2].strip('"'), sys.argv[1])
    # elif len(sys.argv) == 2:
    #     arg = sys.argv[1]
    #     if os.path.exists(arg):
    #         if arg.endswith('content.txt'):
    #             exec_res = exec_down(arg, os.path.dirname(arg), "", "")
    #             print("down count ", exec_res)
    #         else:
    #             kill_down(arg)
