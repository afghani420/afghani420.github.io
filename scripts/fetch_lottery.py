# -*- coding: utf-8 -*-
import os
import json
import sys
import time
import hashlib
import requests
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding='utf-8')

import anthropic

SERPER_KEY = os.environ['SERPER_API_KEY']
ANTHROPIC_KEY = os.environ['ANTHROPIC_API_KEY']

DATA_FILE = 'sake-lottery/data/lotteries.json'

SEARCH_QUERIES = [
    'ウイスキー 抽選販売 応募 購入権 2026',
    '日本酒 限定 抽選販売 応募 2026',
    'バーボン ウイスキー 抽選 購入権',
    '焼酎 限定 抽選販売 応募',
    'スコッチ ウイスキー 抽選販売',
    '限定酒 抽選 応募受付中',
    'ラム ジン リキュール 限定 抽選販売',
]

client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)


def search_serper(query):
    resp = requests.post(
        'https://google.serper.dev/search',
        headers={'X-API-KEY': SERPER_KEY, 'Content-Type': 'application/json'},
        json={'q': query, 'gl': 'jp', 'hl': 'ja', 'num': 50},
        timeout=15
    )
    resp.raise_for_status()
    return resp.json().get('organic', [])


def extract_lotteries(results, query):
    if not results:
        return []

    text = '\n\n'.join([
        f"タイトル: {r.get('title', '')}\nURL: {r.get('link', '')}\n概要: {r.get('snippet', '')}"
        for r in results
    ])

    today = datetime.now(timezone.utc).strftime('%Y年%m月%d日')

    prompt = f"""今日は{today}です。以下は「{query}」の検索結果です。

お酒の「購入権」の抽選販売情報のみ抽出してください。
除外: プレゼント・懸賞・無料当選・試飲会・イベント参加権

各抽選情報をJSON配列で返してください:
[
  {{
    "product": "商品名（ブランド名と品番を含む正式名称）",
    "price_text": "価格表示（例: '5,000円'、税込なら'5,500円（税込）'）、不明はnull",
    "price": 数値（円）または null,
    "category": "whisky"（ウイスキー・バーボン・スコッチ・アイリッシュ等）/ "sake"（日本酒・焼酎・清酒・泡盛等）/ "other"（ワイン・ジン・ラム・ビール等）,
    "is_official": true（メーカー・蔵元・輸入元の公式サイト）/ false（小売店・EC・酒販店）,
    "source_name": "サイト名または店舗名",
    "url": "応募ページのURL",
    "start_date": "応募開始日時（ISO 8601、例: '2026-04-20T10:00:00+09:00'）または null",
    "end_date": "応募終了日時（ISO 8601）または null",
    "is_ended": true（テキストに「終了」「受付終了」「締め切り」「終了済み」等の記述があればtrue）/ false,
    "notes": "抽選日・当選発表日・本数制限等の補足（なければnull）"
  }}
]

注意:
- 確実に抽選販売とわかる情報のみ含める
- 同じ商品が複数の検索結果に出た場合は1件のみ
- URLが不明・不完全な場合は除外
- 価格・応募期間はスニペットに記載があれば必ず抽出する（「〜円」「〜月〜日」等）

検索結果:
{text}

JSONのみ返してください。```json ... ```で囲んでください。"""

    message = client.messages.create(
        model='claude-haiku-4-5',
        max_tokens=3000,
        messages=[{'role': 'user', 'content': prompt}]
    )

    raw = message.content[0].text
    if '```json' in raw:
        raw = raw.split('```json')[1].split('```')[0].strip()
    elif '```' in raw:
        raw = raw.split('```')[1].split('```')[0].strip()

    try:
        items = json.loads(raw)
        return items if isinstance(items, list) else []
    except Exception as e:
        print(f"JSON parse error: {e}\nRaw: {raw[:200]}")
        return []


def make_id(url, product):
    key = f"{url}:{product}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


def load_existing():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def save(data):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def parse_date(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00'))
    except Exception:
        return None


ENDED_KEYWORDS = ['終了', '受付終了', '締め切り', '終了済', '応募終了', '受付を終了', '終了しました']

def compute_status(item):
    now = datetime.now(timezone.utc)
    start = parse_date(item.get('start_date'))
    end = parse_date(item.get('end_date'))

    if end and end < now:
        return 'ended'
    if item.get('is_ended'):
        return 'ended'
    notes = (item.get('notes') or '') + (item.get('product') or '')
    if any(kw in notes for kw in ENDED_KEYWORDS):
        return 'ended'
    if start and start > now:
        return 'upcoming'
    return 'active'


def main():
    existing = load_existing()
    existing_map = {item['id']: item for item in existing}

    now_iso = datetime.now(timezone.utc).isoformat()
    new_count = 0

    for query in SEARCH_QUERIES:
        print(f"Searching: {query}")
        try:
            results = search_serper(query)
            items = extract_lotteries(results, query)
            for item in items:
                if not item.get('url') or not item.get('product'):
                    continue
                item_id = make_id(item['url'], item['product'])
                if item_id not in existing_map:
                    item['id'] = item_id
                    item['found_at'] = now_iso
                    existing_map[item_id] = item
                    new_count += 1
                else:
                    # update dates/price if we got better info
                    existing_item = existing_map[item_id]
                    for field in ('price', 'price_text', 'start_date', 'end_date', 'notes'):
                        if item.get(field) and not existing_item.get(field):
                            existing_item[field] = item[field]
            time.sleep(1)
        except Exception as e:
            print(f"Error for '{query}': {e}")

    all_items = list(existing_map.values())

    # recompute status
    for item in all_items:
        item['status'] = compute_status(item)

    # remove ended items older than 30 days (keep recent ended for reference)
    now = datetime.now(timezone.utc)
    def keep(item):
        if item['status'] != 'ended':
            return True
        end = parse_date(item.get('end_date'))
        if end:
            return (now - end).days <= 30
        found = parse_date(item.get('found_at'))
        if found:
            return (now - found).days <= 30
        return True

    all_items = [i for i in all_items if keep(i)]

    # sort: active → upcoming → ended, then by end_date
    status_order = {'active': 0, 'upcoming': 1, 'ended': 2}
    def sort_key(x):
        s = status_order.get(x.get('status', 'active'), 0)
        ed = parse_date(x.get('end_date'))
        if ed:
            ts = ed.timestamp()
        else:
            ts = 9999999999 if x.get('status') == 'upcoming' else 0
        return (s, ts)

    all_items.sort(key=sort_key)
    all_items = all_items[:300]

    save(all_items)
    print(f"Done. Total: {len(all_items)}, New: {new_count}")


if __name__ == '__main__':
    main()
