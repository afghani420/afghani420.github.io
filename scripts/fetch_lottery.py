# -*- coding: utf-8 -*-
import os
import json
import re
import sys
import time
import hashlib
import requests
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding='utf-8')

import anthropic

BRAVE_KEY = os.environ['BRAVE_API_KEY']
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


def search_brave(query):
    resp = requests.get(
        'https://api.search.brave.com/res/v1/web/search',
        headers={
            'X-Subscription-Token': BRAVE_KEY,
            'Accept': 'application/json',
            'Accept-Encoding': 'gzip',
        },
        params={'q': query, 'count': 20, 'country': 'JP', 'search_lang': 'jp'},
        timeout=15
    )
    resp.raise_for_status()
    return resp.json().get('web', {}).get('results', [])


def extract_lotteries(results, query):
    if not results:
        return []

    text = '\n\n'.join([
        f"タイトル: {r.get('title', '')}\nURL: {r.get('url', '')}\n概要: {r.get('description', '')}"
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
    "is_ended": true（以下のいずれかに該当する場合true）/ false,
    "notes": "抽選日・当選発表日・本数制限等の補足（なければnull）"
  }}
]

注意:
- 確実に抽選販売とわかる情報のみ含める
- 同じ商品が複数の検索結果に出た場合は1件のみ
- URLが不明・不完全な場合は除外
- 価格・応募期間はスニペットに記載があれば必ず抽出する（「〜円」「〜月〜日」等）
- is_ended=trueにする条件: 「終了」「受付終了」「締め切り」の記述がある / URLやタイトル・概要に今年（{datetime.now(timezone.utc).year}年）より前の年が含まれる / 応募期間が明らかに過去である
- is_ended=falseにする条件: 今まさに応募受付中、または開始予定が確認できる場合のみ。判断できない場合はis_ended=trueとする

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

def _has_past_year(text):
    current_year = datetime.now(timezone.utc).year
    years = re.findall(r'\b20\d{2}\b', text or '')
    return years and all(int(y) < current_year for y in years)

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
    # URLやnotesに過去年のみ含まれる場合は終了扱い
    url_and_notes = (item.get('url') or '') + ' ' + (item.get('notes') or '')
    if _has_past_year(url_and_notes):
        return 'ended'
    if start and start > now:
        return 'upcoming'
    return 'active'


def verify_active_item(item):
    """URLを実際に取得してClaudeに受付状況を確認する。終了なら True を返す。"""
    url = item.get('url', '')
    if not url:
        return False
    try:
        resp = requests.get(
            url,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'},
            timeout=10,
            allow_redirects=True
        )
        if resp.status_code == 404:
            print(f"  404 → 終了扱い: {url[:60]}")
            return True
        if resp.status_code != 200:
            return False
        text = re.sub(r'<[^>]+>', ' ', resp.text[:10000])
        text = re.sub(r'\s+', ' ', text).strip()[:3000]
    except Exception as e:
        print(f"  フェッチ失敗 [{url[:50]}]: {e}")
        return False

    product = item.get('product', '')
    prompt = f"""以下のWebページの内容を見て、「{product}」の抽選販売がまだ応募受付中か判断してください。

ページ内容（一部）:
{text}

以下のJSONのみで返してください:
{{"is_accepting": true または false, "reason": "判断理由（1行）"}}

注意: 明確に終了・SOLD OUT・締め切り済みと確認できる場合のみ false。不明な場合は true。"""

    try:
        message = client.messages.create(
            model='claude-haiku-4-5',
            max_tokens=150,
            messages=[{'role': 'user', 'content': prompt}]
        )
        raw = message.content[0].text.strip()
        if '```' in raw:
            raw = raw.split('```')[1].split('```')[0].strip()
            if raw.startswith('json'):
                raw = raw[4:].strip()
        result = json.loads(raw)
        is_accepting = result.get('is_accepting', True)
        reason = result.get('reason', '')
        print(f"  検証: {product[:30]} → {'受付中' if is_accepting else '終了'} ({reason})")
        return not is_accepting
    except Exception as e:
        print(f"  検証パースエラー [{product[:30]}]: {e}")
        return False


def build_site_queries(existing, max_sites=5, min_count=2, days=90):
    """直近N日以内に発見されたエントリが多い上位ドメインのsite:クエリを自動生成する"""
    from urllib.parse import urlparse
    from collections import Counter
    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
    domain_count = Counter()
    for item in existing:
        found = parse_date(item.get('found_at'))
        if not found or found.timestamp() < cutoff:
            continue
        try:
            domain = urlparse(item['url']).netloc
            if domain:
                domain_count[domain] += 1
        except Exception:
            pass
    top_domains = [d for d, c in domain_count.most_common(max_sites) if c >= min_count]
    queries = [f'site:{d} 抽選 応募受付中' for d in top_domains]
    if queries:
        print(f"自動site:クエリ追加: {queries}")
    return queries


def main():
    existing = load_existing()
    existing_map = {item['id']: item for item in existing}

    now_iso = datetime.now(timezone.utc).isoformat()
    new_count = 0

    all_queries = SEARCH_QUERIES + build_site_queries(existing)

    for query in all_queries:
        print(f"Searching: {query}")
        try:
            results = search_brave(query)
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
                    # is_ended は true への更新のみ許可
                    if item.get('is_ended') and not existing_item.get('is_ended'):
                        existing_item['is_ended'] = True
            time.sleep(1)
        except Exception as e:
            print(f"Error for '{query}': {e}")

    all_items = list(existing_map.values())

    # アクティブアイテムをページ直接フェッチで検証
    print("=== アクティブアイテム検証 ===")
    for item in all_items:
        if item.get('is_ended'):
            continue
        temp_status = compute_status(item)
        if temp_status == 'active':
            ended = verify_active_item(item)
            if ended:
                item['is_ended'] = True
            time.sleep(0.5)

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
