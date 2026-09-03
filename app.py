from flask import Flask, request, jsonify
from flask_cors import CORS
from curl_cffi import requests as cffi_requests
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

app = Flask(__name__)
CORS(app)
app.config['JSONIFY_PRETTYPRINT_REGULAR'] = True


GROWW_HEADERS = {
    'User-Agent':      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36',
    'Accept':          'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer':         'https://groww.in/mutual-funds',
    'X-App-Id':        'growwWeb',
    'X-Platform':      'web',
    'X-Device-Type':   'desktop',
    'Origin':          'https://groww.in',
}


@app.route('/groww')
def groww():
    scheme_code = request.args.get('code')
    if not scheme_code:
        return jsonify({'error': 'code required e.g. ?code=118632'}), 400

    start_time = datetime.now(timezone.utc)

    try:
        search_id          = None
        fund_house         = None
        fund_name          = None
        scheme_name        = None
        direct_scheme_name = None
        scheme_type        = None
        sub_category       = None
        category           = None
        nav_from_filter    = None
        risk_from_filter   = None
        risk_rating        = None
        mean_return        = None
        min_investment     = None
        min_sip            = None
        lumpsum_allowed    = None
        sip_allowed        = None
        sip_return1y       = None
        sip_return3y       = None
        sip_return5y       = None
        page               = 0

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
                return jsonify({
                    'error': 'Groww filter API blocked — try after 1 minute',
                    'code':  'FILTER_BLOCKED'
                }), 503

            data  = r.json()
            funds = data.get('content', [])
            if not funds:
                break

            match = next((f for f in funds if str(f.get('scheme_code')) == str(scheme_code)), None)
            if match:
                search_id          = match['search_id']
                fund_house         = match['fund_house']
                fund_name          = match.get('fund_name')
                scheme_name        = match.get('scheme_name')
                direct_scheme_name = match.get('direct_scheme_name')
                scheme_type        = match.get('scheme_type')
                sub_category       = match.get('sub_category')
                category           = match.get('category')
                nav_from_filter    = match.get('nav')
                risk_from_filter   = match.get('risk')
                risk_rating        = match.get('risk_rating')
                mean_return        = match.get('mean_return')
                min_investment     = match.get('min_investment_amount')
                min_sip            = match.get('min_sip_investment')
                lumpsum_allowed    = match.get('lumpsum_allowed')
                sip_allowed        = match.get('sip_allowed')
                sip_return1y       = match.get('sip_return1y')
                sip_return3y       = match.get('sip_return3y')
                sip_return5y       = match.get('sip_return5y')
                break
            page += 1

        if not search_id:
            return jsonify({
                'error':         'Fund not found in Groww — may be Regular plan or not listed',
                'pages_checked': page,
                'code':          'NOT_FOUND'
            }), 404

        def fetch_scheme():
            return cffi_requests.get(
                f'https://groww.in/v1/api/data/mf/web/v6/scheme/search/{search_id}',
                headers=GROWW_HEADERS,
                impersonate='chrome120',
                timeout=15
            )

        def fetch_stats():
            return cffi_requests.get(
                f'https://groww.in/v1/api/data/mf/web/v1/scheme/portfolio/{scheme_code}/stats',
                headers=GROWW_HEADERS,
                impersonate='chrome120',
                timeout=15
            )

        with ThreadPoolExecutor() as ex:
            r2 = ex.submit(fetch_scheme).result()
            r3 = ex.submit(fetch_stats).result()

        if r2.text.startswith('<!DOCTYPE') or r3.text.startswith('<!DOCTYPE'):
            return jsonify({
                'error': 'Groww scheme API blocked — try after 1 minute',
                'code':  'SCHEME_BLOCKED'
            }), 503

        d  = r2.json()
        ps = r3.json()

        rs = d.get('return_stats', [{}])
        rs = rs[0] if isinstance(rs, list) else rs

        # All holdings returned raw — no filtering by nature_name
        all_holdings = [
            {
                'company':      h['company_name'],
                'nature':       h['nature_name'],
                'sector':       h['sector_name'],
                'corpus_per':   h['corpus_per'],
                'market_value': h['market_value'],
                'instrument':   h['instrument_name'],
                'rating':       h.get('rating'),
            }
            for h in d.get('holdings', [])
        ]

        elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

        return jsonify({
            # Identity
            'scheme_code':          scheme_code,
            'search_id':            search_id,
            'fund_house':           fund_house,
            'fund_name':            fund_name,
            'scheme_name':          scheme_name,
            'direct_scheme_name':   direct_scheme_name,
            'scheme_type':          scheme_type,
            'sub_category':         sub_category,
            'category':             category,

            # Holdings — all items, no filter, nature field tells EQUITY/DEBT/CASH
            'holdings':             all_holdings,
            'total_holdings_count': len(all_holdings),

            # Portfolio Stats
            'equity_sector':        ps.get('equity_sector_per'),
            'debt_sector':          ps.get('debt_sector_per'),
            'asset_allocation':     ps.get('asset_allocation'),
            'large_cap':            ps.get('large_cap'),
            'mid_cap':              ps.get('mid_cap'),
            'small_cap':            ps.get('small_cap'),
            'pe':                   ps.get('pe'),
            'pb':                   ps.get('pb'),
            'aum':                  ps.get('aum'),
            'portfolio_turnover':   ps.get('portfolio_turnover'),
            'total_holdings':       ps.get('total_holdings'),
            'debt_per':             ps.get('debt_per'),
            'equity_per':           ps.get('equity_per'),
            'cash_per':             ps.get('cash_per'),
            'average_maturity':     ps.get('average_maturity'),
            'modified_duration':    ps.get('modified_duration'),
            'yield_to_maturity':    ps.get('yield_to_maturity'),

            # Returns
            'return1d':             rs.get('return1d'),
            'return1w':             rs.get('return1w'),
            'return1m':             rs.get('return1m'),
            'return3m':             rs.get('return3m'),
            'return6m':             rs.get('return6m'),
            'return1y':             rs.get('return1y'),
            'return3y':             rs.get('return3y'),
            'return5y':             rs.get('return5y'),
            'return10y':            rs.get('return10y'),

            # SIP Returns
            'sip_return1y':         sip_return1y,
            'sip_return3y':         sip_return3y,
            'sip_return5y':         sip_return5y,

            # Category Comparison
            'cat_return1y':         rs.get('cat_return1y'),
            'cat_return3y':         rs.get('cat_return3y'),
            'cat_return5y':         rs.get('cat_return5y'),
            'rank1y':               rs.get('rank1yr'),
            'rank3y':               rs.get('rank3yr'),
            'rank5y':               rs.get('rank5yr'),

            # Risk Metrics
            'sharpe':               rs.get('sharpe_ratio'),
            'sortino':              rs.get('sortino_ratio'),
            'beta':                 rs.get('beta'),
            'alpha':                rs.get('alpha'),
            'std_dev':              rs.get('standard_deviation'),
            'risk':                 risk_from_filter,
            'risk_rating':          risk_rating,
            'mean_return':          mean_return,

            # Fund Info
            'nav':                  nav_from_filter,
            'expense_ratio':        d.get('expense_ratio'),
            'groww_rating':         d.get('groww_rating'),
            'exit_load':            d.get('exit_load'),
            'benchmark':            d.get('benchmark_name'),
            'fund_manager':         d.get('fund_manager'),
            'launch_date':          d.get('launch_date'),
            'isin':                 d.get('isin'),
            'min_investment':       min_investment,
            'min_sip':              min_sip,
            'lumpsum_allowed':      lumpsum_allowed,
            'sip_allowed':          sip_allowed,

            # Analysis
            'pros':                 [a['analysis_desc'] for a in d.get('analysis', []) if a.get('analysis_type') == 'PROS'],
            'cons':                 [a['analysis_desc'] for a in d.get('analysis', []) if a.get('analysis_type') == 'CONS'],

            # Meta
            'fetchedAt':            start_time.isoformat(),
            'fetchTimeMs':          elapsed_ms,
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─── /nav — NAV history for multiple funds (new, separate) ───────────────────
# Input:
#   codes = comma-separated AMFI scheme codes e.g. 122639,118632,127042
#   from  = YYYY-MM-DD | all | omit → full history
#   to    = YYYY-MM-DD | today | omit → no end filter
#
# Output per code: { name, count, navData: [{ date: YYYY-MM-DD, nav }] }

def ts_to_date_ist(ms):
    ist = datetime.utcfromtimestamp(ms / 1000) + timedelta(hours=5, minutes=30)
    return ist.strftime('%Y-%m-%d')

def date_to_ts_ist(date_str):
    dt = datetime.strptime(date_str, '%Y-%m-%d')
    ist_midnight = dt - timedelta(hours=5, minutes=30)
    return int(ist_midnight.timestamp() * 1000)

def months_between(from_date, to_date):
    d1 = datetime.strptime(from_date, '%Y-%m-%d')
    d2 = datetime.strptime(to_date,   '%Y-%m-%d')
    diff = (d2.year - d1.year) * 12 + (d2.month - d1.month)
    return max(1, diff + 1)

def today_ist():
    return (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime('%Y-%m-%d')

def fetch_nav_for_code(code, groww_url, from_ts, to_ts):
    try:
        r = cffi_requests.get(
            groww_url.replace('{CODE}', code),
            headers=GROWW_HEADERS,
            impersonate='chrome120',
            timeout=15
        )
        if not r.ok:
            return code, {'error': f'Groww API error: HTTP {r.status_code}'}

        data  = r.json()
        folio = data.get('folio')
        if not folio or not isinstance(folio.get('data'), list):
            return code, {'error': 'Unexpected Groww response format'}

        filtered = [
            row for row in folio['data']
            if (from_ts is None or row[0] >= from_ts) and
               (to_ts   is None or row[0] <= to_ts)
        ]

        return code, {
            'name':    folio.get('name', ''),
            'count':   len(filtered),
            'navData': [{'date': ts_to_date_ist(row[0]), 'nav': row[1]} for row in filtered],
        }

    except Exception as e:
        return code, {'error': str(e)}


@app.route('/nav')
def nav():
    import re
    start_time = datetime.now(timezone.utc)

    codes_param = request.args.get('codes', '').strip()
    if not codes_param:
        return jsonify({'error': 'codes param required e.g. codes=122639 or codes=122639,118632,127042'}), 400

    codes = [c.strip() for c in codes_param.split(',') if c.strip()]
    if any(not c.isdigit() for c in codes):
        return jsonify({'error': 'All codes must be numeric e.g. codes=122639,118632'}), 400

    from_param = request.args.get('from', 'all').strip().lower()
    to_param   = request.args.get('to',   '').strip().lower()

    date_re = re.compile(r'^\d{4}-\d{2}-\d{2}$')
    if from_param != 'all' and not date_re.match(from_param):
        return jsonify({'error': 'from must be YYYY-MM-DD, "all", or omitted e.g. from=2020-01-01'}), 400
    if to_param and to_param != 'today' and not date_re.match(to_param):
        return jsonify({'error': 'to must be YYYY-MM-DD, "today", or omitted e.g. to=2026-01-01'}), 400

    from_date = None if from_param == 'all' else from_param
    to_date   = today_ist() if to_param == 'today' else (to_param or None)

    if from_date:
        end    = to_date or today_ist()
        months = months_between(from_date, end)
        groww_url = f'https://groww.in/v1/api/data/mf/web/v1/scheme/{{CODE}}/graph?benchmark=false&months={months}'
    else:
        groww_url = 'https://groww.in/v1/api/data/mf/web/v1/scheme/{CODE}/graph'

    from_ts = date_to_ts_ist(from_date) if from_date else None
    to_ts   = date_to_ts_ist(to_date) + 86400000 - 1 if to_date else None

    with ThreadPoolExecutor() as ex:
        futures = [ex.submit(fetch_nav_for_code, code, groww_url, from_ts, to_ts) for code in codes]
        results = {code: result for code, result in (f.result() for f in futures)}

    elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

    from flask import Response
    import json
    return Response(
        json.dumps({
            'fetchedAt':   start_time.isoformat(),
            'fetchTimeMs': elapsed_ms,
            'codes':       codes,
            'from':        from_date or 'all',
            'to':          to_date   or 'all',
            'count':       len(codes),
            'data':        results,
        }, indent=2),
        mimetype='application/json'
    )


@app.route('/ping')
def ping():
    return 'ok', 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
