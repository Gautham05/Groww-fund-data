from flask import Flask, request, jsonify
from flask_cors import CORS
from curl_cffi import requests as cffi_requests
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import threading
import time

app = Flask(__name__)
CORS(app)

# ─── Self ping to prevent Render free tier sleep ───
def keep_alive():
    time.sleep(60)  # wait 1 min after startup before first ping
    while True:
        try:
            cffi_requests.get('https://groww-fund-data.onrender.com/ping', timeout=10)
        except:
            pass
        time.sleep(5 * 60)  # ping every 14 minutes

threading.Thread(target=keep_alive, daemon=True).start()

GROWW_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://groww.in/mutual-funds',
    'X-App-Id': 'growwWeb',
    'X-Platform': 'web',
    'X-Device-Type': 'desktop',
    'Origin': 'https://groww.in',
}


@app.route('/groww')
def groww():
    scheme_code = request.args.get('code')
    if not scheme_code:
        return jsonify({'error': 'code required e.g. ?code=118632'}), 400

    start_time = datetime.now(timezone.utc)

    try:
        # Step 1 - find search_id using filter API pagination
        # curl_cffi impersonates Chrome120 at TLS level
        # size=100 covers all 3403 funds (old size=50 only covered 2000)
        search_id    = None
        fund_house   = None
        sip_return1y = None
        sip_return3y = None
        sip_return5y = None
        page = 0

        while page <= 40:
            r = cffi_requests.get(
                f'https://groww.in/v1/api/search/v3/query/filter_derived_data/st_filter'
                f'?available_for_investment=true&doc_type=scheme&index=false'
                f'&page={page}&plan_type=Direct&size=100&sort_by=3',
                headers=GROWW_HEADERS,
                impersonate='chrome120',
                timeout=10
            )
            if r.text.startswith('<!DOCTYPE'):
                return jsonify({'error': 'Groww filter API blocked — try after 1 minute', 'code': 'FILTER_BLOCKED'}), 503

            data  = r.json()
            funds = data.get('content', [])
            if not funds:
                break

            match = next((f for f in funds if str(f.get('scheme_code')) == str(scheme_code)), None)
            if match:
                search_id    = match['search_id']
                fund_house   = match['fund_house']
                sip_return1y = match.get('sip_return1y')
                sip_return3y = match.get('sip_return3y')
                sip_return5y = match.get('sip_return5y')
                break
            page += 1

        if not search_id:
            return jsonify({'error': 'Fund not found in Groww — may be Regular plan or not listed', 'pages_checked': page, 'code': 'NOT_FOUND'}), 404

        # Step 2 - fetch scheme data + portfolio stats in parallel
        def fetch_scheme():
            return cffi_requests.get(
                f'https://groww.in/v1/api/data/mf/web/v6/scheme/search/{search_id}',
                headers=GROWW_HEADERS, impersonate='chrome120', timeout=15
            )

        def fetch_stats():
            return cffi_requests.get(
                f'https://groww.in/v1/api/data/mf/web/v1/scheme/portfolio/{scheme_code}/stats',
                headers=GROWW_HEADERS, impersonate='chrome120', timeout=15
            )

        with ThreadPoolExecutor() as ex:
            f2 = ex.submit(fetch_scheme)
            f3 = ex.submit(fetch_stats)
            r2 = f2.result()
            r3 = f3.result()

        if r2.text.startswith('<!DOCTYPE') or r3.text.startswith('<!DOCTYPE'):
            return jsonify({'error': 'Groww scheme API blocked — try after 1 minute', 'code': 'SCHEME_BLOCKED'}), 503

        d  = r2.json()
        ps = r3.json()

        rs = d.get('return_stats', [{}])
        rs = rs[0] if isinstance(rs, list) else rs

        all_holdings    = d.get('holdings', [])
        equity_holdings = [
            {'company': h['company_name'], 'sector': h['sector_name'], 'corpus_per': h['corpus_per'], 'market_value': h['market_value'], 'instrument': h['instrument_name']}
            for h in all_holdings if h.get('nature_name') == 'EQUITY'
        ]
        debt_holdings = [
            {'company': h['company_name'], 'nature': h['nature_name'], 'sector': h['sector_name'], 'corpus_per': h['corpus_per'], 'market_value': h['market_value'], 'instrument': h['instrument_name'], 'rating': h.get('rating')}
            for h in all_holdings if h.get('nature_name') != 'EQUITY'
        ]

        elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

        return jsonify({
            'scheme_code': scheme_code, 'search_id': search_id, 'fund_house': fund_house,
            'equity_holdings': equity_holdings, 'debt_holdings': debt_holdings, 'total_holdings_count': len(all_holdings),
            'sector': ps.get('equity_sector_per'), 'debt_sector': ps.get('debt_sector_per'),
            'asset_allocation': ps.get('asset_allocation'),
            'large_cap': ps.get('large_cap'), 'mid_cap': ps.get('mid_cap'), 'small_cap': ps.get('small_cap'),
            'pe': ps.get('pe'), 'pb': ps.get('pb'), 'aum': ps.get('aum'),
            'portfolio_turnover': ps.get('portfolio_turnover'), 'total_holdings': ps.get('total_holdings'),
            'debt_per': ps.get('debt_per'), 'equity_per': ps.get('equity_per'), 'cash_per': ps.get('cash_per'),
            'average_maturity': ps.get('average_maturity'), 'modified_duration': ps.get('modified_duration'), 'yield_to_maturity': ps.get('yield_to_maturity'),
            'return1d': rs.get('return1d'), 'return1w': rs.get('return1w'), 'return1m': rs.get('return1m'),
            'return3m': rs.get('return3m'), 'return6m': rs.get('return6m'), 'return1y': rs.get('return1y'),
            'return3y': rs.get('return3y'), 'return5y': rs.get('return5y'), 'return10y': rs.get('return10y'),
            'sip_return1y': sip_return1y, 'sip_return3y': sip_return3y, 'sip_return5y': sip_return5y,
            'cat_return1y': rs.get('cat_return1y'), 'cat_return3y': rs.get('cat_return3y'), 'cat_return5y': rs.get('cat_return5y'),
            'rank1y': rs.get('rank1yr'), 'rank3y': rs.get('rank3yr'), 'rank5y': rs.get('rank5yr'),
            'sharpe': rs.get('sharpe_ratio'), 'sortino': rs.get('sortino_ratio'),
            'beta': rs.get('beta'), 'alpha': rs.get('alpha'), 'std_dev': rs.get('standard_deviation'), 'risk': rs.get('risk'),
            'expense_ratio': d.get('expense_ratio'), 'groww_rating': d.get('groww_rating'),
            'exit_load': d.get('exit_load'), 'benchmark': d.get('benchmark_name'),
            'fund_manager': d.get('fund_manager'), 'launch_date': d.get('launch_date'), 'isin': d.get('isin'),
            'pros': [a['analysis_desc'] for a in d.get('analysis', []) if a.get('analysis_type') == 'PROS'],
            'cons': [a['analysis_desc'] for a in d.get('analysis', []) if a.get('analysis_type') == 'CONS'],
            'fetchedAt': start_time.isoformat(),
            'fetchTimeMs': elapsed_ms,
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/ping')
def ping():
    return 'ok', 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
