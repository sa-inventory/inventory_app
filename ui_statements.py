import streamlit as st
import pandas as pd
import datetime
import base64
import uuid
from utils import load_user_settings, num_to_korean

def render_statement_list(db):
    st.header("거래명세서 조회")
    st.info("발행된 거래명세서 내역을 조회하고 재출력합니다. (수정 불가)")

    # [NEW] Handle quick link from shipping history
    go_to_stmt_id = st.session_state.pop('go_to_statement', None)
    if go_to_stmt_id:
        st.session_state['stmt_search_no'] = go_to_stmt_id
        # Clear other filters for clarity
        st.session_state['stmt_search_cust'] = ""
        st.session_state['stmt_date_range'] = []

    # [FIX] Initialize session state for filters to prevent widget/session state conflicts.
    today = datetime.date.today()
    if 'stmt_date_range' not in st.session_state:
        st.session_state['stmt_date_range'] = [today - datetime.timedelta(days=30), today]
    if 'stmt_search_cust' not in st.session_state:
        st.session_state['stmt_search_cust'] = ""
    if 'stmt_search_no' not in st.session_state:
        st.session_state['stmt_search_no'] = ""

    # 검색 필터
    with st.expander("검색", expanded=True):
        c1, c2, c3 = st.columns([1, 1, 2])
        # [FIX] Use the session state as the single source of truth for the widget's value.
        date_range = c1.date_input("발행일 기간", key="stmt_date_range")
        search_cust = c2.text_input("거래처명", key="stmt_search_cust")
        search_no = c3.text_input("일련번호", key="stmt_search_no")

    # 데이터 조회
    query = db.collection("statements").order_by("issue_date", direction="DESCENDING")
    
    # 날짜 필터 (메모리 필터링 또는 쿼리 필터링)
    # Firestore 복합 인덱스 문제 회피를 위해 날짜는 쿼리로, 나머지는 메모리로 처리 권장
    if len(date_range) == 2:
        start_dt = datetime.datetime.combine(date_range[0], datetime.time.min)
        end_dt = datetime.datetime.combine(date_range[1], datetime.time.max)
        query = query.where("issue_date", ">=", start_dt).where("issue_date", "<=", end_dt)
    
    docs = query.stream()
    rows = []
    for doc in docs:
        d = doc.to_dict()
        
        # 메모리 필터링
        if search_cust and search_cust not in d.get('customer', ''): continue
        if search_no and search_no not in d.get('statement_no', ''): continue
        
        rows.append(d)

    if not rows:
        st.info("조회된 거래명세서가 없습니다.")
        return

    df = pd.DataFrame(rows)
    
    # 날짜 포맷팅
    if 'issue_date' in df.columns:
        df['issue_date'] = df['issue_date'].apply(lambda x: x.strftime('%Y-%m-%d') if hasattr(x, 'strftime') else str(x)[:10])

    # 목록 표시
    st.write("🔽 상세 내용을 확인할 명세서를 선택하세요.")
    
    col_map = {
        "statement_no": "일련번호", "issue_date": "발행일", "customer": "거래처",
        "total_amount": "총액", "supply_price": "공급가액", "tax": "세액"
    }
    display_cols = ["statement_no", "issue_date", "customer", "total_amount", "supply_price", "tax"]
    
    selection = st.dataframe(
        df[display_cols].rename(columns=col_map),
        width="stretch",
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="stmt_list_table"
    )

    if selection.selection.rows:
        idx = selection.selection.rows[0]
        sel_row = df.iloc[idx]
        stmt_data = sel_row.to_dict() # 전체 데이터 (items 포함)
        
        st.divider()
        st.subheader(f"📄 명세서 상세: {stmt_data['statement_no']} ({stmt_data['customer']})")
        
        # 상세 품목 표시
        items = stmt_data.get('items', [])
        if items:
            st.dataframe(pd.DataFrame(items), hide_index=True, use_container_width=True)
            st.caption(f"합계: {stmt_data.get('total_amount', 0):,}원 (공급가 {stmt_data.get('supply_price', 0):,} + 세액 {stmt_data.get('tax', 0):,})")
        
        # 재출력 버튼
        if st.button("🖨️ 명세서 재출력", type="primary"):
            print_statement(db, stmt_data)

def print_statement(db, stmt_data):
    # 설정 로드 (현재 설정 사용)
    user_id = st.session_state.get("user_id")
    default_settings = {
        "opt_type": "공급받는자용", "opt_show_sign": True, "opt_hide_price": False, 
        "opt_show_logo": True, "opt_logo_height": 50, "opt_show_stamp": True, 
        "opt_sw": 50, "opt_st": -10, "opt_sr": 0,
        "opt_show_appr": False, "opt_ac": 3,
        "bo": 1.0, "bi": 0.5, "tb": 1.0,
        "mt": 10, "mb": 10, "ml": 10, "mr": 10,
        "title": "거 래 명 세 서", "ts": 24, "fs": 12, "pad": 5,
        "rows": 18,
        "w_date": 5, "w_item": 25, "w_spec": 15, "w_qty": 8,
        "w_price": 10, "w_supply": 12, "w_tax": 10, "w_note": 15,
        "opt_bank": True, "opt_note": ""
    }
    s = load_user_settings(user_id, "stmt_settings", default_settings)
    
    # 회사 정보 (로고/직인용)
    comp_doc = db.collection("settings").document("company_info").get()
    comp_info = comp_doc.to_dict() if comp_doc.exists else {}
    
    # 데이터 준비
    items = stmt_data.get('items', [])
    supplier = stmt_data.get('supplier_info', {})
    recipient = stmt_data.get('recipient_info', {})
    grand_total = stmt_data.get('total_amount', 0)
    total_supply = stmt_data.get('supply_price', 0)
    total_tax = stmt_data.get('tax', 0)
    
    # HTML 생성 (ui_shipping.py와 유사하지만 저장된 스냅샷 데이터 사용)
    stamp_b64 = comp_info.get('stamp_img') if s['opt_show_stamp'] else None
    stamp_html = f"<img src='data:image/png;base64,{stamp_b64}' class='stamp'>" if stamp_b64 else ""
    logo_b64 = comp_info.get('logo_img') if s['opt_show_logo'] else None
    logo_html = f"<img src='data:image/png;base64,{logo_b64}' class='logo'>" if logo_b64 else ""
    
    # 결재란
    appr_html = ""
    if s['opt_show_appr']:
        appr_titles = [s.get(f"opt_at_{j}", "") for j in range(s['opt_ac'])]
        appr_html = '<table class="appr-table"><tr><td rowspan="2" class="appr-header">결<br>재</td>'
        for t in appr_titles:
            appr_html += f'<td>{t}</td>'
        appr_html += '</tr><tr>'
        for _ in range(s['opt_ac']):
            appr_html += '<td class="appr-box"></td>'
        appr_html += '</tr></table>'
    
    sign_html = "<div style='margin-top:5px; text-align:right;'><strong>인수자 : ________________ (인)</strong></div>" if s['opt_show_sign'] else ""
    bank_info = f"입금계좌: {comp_info.get('bank_name','')} {comp_info.get('bank_account','')}" if s['opt_bank'] else ""

    html_template = f"""
    <html>
    <head>
        <style>
            * {{ box-sizing: border-box; }}
            body {{ font-family: 'Malgun Gothic', sans-serif; padding: 20px; }}
            .container {{ width: 100%; margin: 0 auto; }}
            .header {{ 
                text-align: center; font-size: {s['ts']}px; font-weight: bold; text-decoration: underline; 
                margin-bottom: 10px; position: relative; min-height: {s['opt_logo_height'] + 10}px;
                display: flex; align-items: center; justify-content: center;
            }}
            .logo {{ position: absolute; left: 0; top: 50%; transform: translateY(-50%); max-height: {s['opt_logo_height']}px; }}
            .top-section {{ display: flex; width: 100%; border: {s['tb']}px solid #333; margin-bottom: 5px; }}
            .supplier, .recipient {{ flex: 1; padding: 5px; }}
            .supplier {{ border-left: {s['bi']}px solid #333; }}
            .row {{ display: flex; margin-bottom: 2px; }}
            .label {{ width: 90px; text-align: center; border: {s['bi']}px solid #ccc; font-size: 12px; display: flex; align-items: center; justify-content: center; }}
            .value {{ flex: 1; padding-left: 5px; border-bottom: 1px solid #ccc; font-size: 12px; }}
            .stamp-box {{ position: relative; }}
            .stamp {{ position: absolute; right: {s['opt_sr']}px; top: {s['opt_st']}px; width: {s['opt_sw']}px; opacity: 0.8; }}
            .main-table {{ width: 100%; border-collapse: collapse; border: {s['bo']}px solid #333; font-size: {s['fs']}px; }}
            .main-table th {{ background: #eee; border: {s['bi']}px solid #333; padding: {s['pad']}px; text-align: center; }}
            .main-table td {{ border: {s['bi']}px solid #333; padding: {s['pad']}px; }}
            .center {{ text-align: center; }}
            .right {{ text-align: right; }}
            .total-row {{ background: #f9f9f9; font-weight: bold; }}
            .total-amount-section {{ border: {s['bo']}px solid #333; border-bottom: none; padding: 8px; text-align: center; font-weight: bold; font-size: 1.1em; background-color: #f9f9f9; }}
            .appr-table {{ float: right; border-collapse: collapse; font-size: 10px; margin-bottom: 5px; }}
            .appr-table td {{ border: 1px solid #333; text-align: center; padding: 2px; }}
            .appr-header {{ width: 20px; background: #eee; }}
            .appr-box {{ width: 50px; height: 40px; }}
            @media print {{ 
                @page {{ size: A4; margin: {s['mt']}mm {s['mr']}mm {s['mb']}mm {s['ml']}mm; }} 
                body {{ padding: 0; -webkit-print-color-adjust: exact; }} 
                .page-break {{ page-break-before: always; }}
            }}
        </style>
    </head>
    <body onload="window.print()">
    """

    def create_page(title_suffix, is_supplier_copy):
        price_header = f'<th width="{s["w_price"]}%">단가</th><th width="{s["w_supply"]}%">공급가액</th><th width="{s["w_tax"]}%">세액</th>' if not s['opt_hide_price'] else ''
        korean_grand_total = num_to_korean(grand_total)
        
        # 날짜 포맷
        issue_dt = stmt_data.get('issue_date')
        if isinstance(issue_dt, str): issue_dt = datetime.datetime.strptime(issue_dt[:10], "%Y-%m-%d")
        elif isinstance(issue_dt, datetime.datetime): pass
        else: issue_dt = datetime.datetime.now()

        page_html = f"""
            <div class="container">
                <div class="header">
                    {logo_html} {s['title']}
                    <span style="font-size: 12px; position: absolute; right: 0; bottom: 0; text-decoration: none; font-weight:normal;">(No. {stmt_data['statement_no']})</span>
                </div>
                {appr_html}
                <div style="clear:both;"></div>
                <div style="display: flex; justify-content: space-between; margin-bottom: 5px; font-size: 12px;">
                    <span style="font-weight: bold;">{f"({title_suffix})" if title_suffix else ""}</span>
                    <span>작성일자: {issue_dt.strftime('%Y년 %m월 %d일')}</span>
                </div>
                <div class="top-section">
                    <div class="recipient">
                        <div style="text-align: center; font-weight: normal; margin-bottom: 5px; border-bottom: {s['bi']}px solid #333; padding-bottom: 2px;">[공급받는자]</div>
                        <div class="row"><div class="label">상호</div><div class="value">{recipient.get('name','')}</div></div>
                        <div class="row"><div class="label">사업자번호</div><div class="value">{recipient.get('biz_num','')}</div></div>
                        <div class="row"><div class="label">대표자</div><div class="value">{recipient.get('rep_name','')}</div></div>
                        <div class="row"><div class="label">주소</div><div class="value">{recipient.get('address','')}</div></div>
                    </div>
                    <div class="supplier">
                        <div style="text-align: center; font-weight: normal; margin-bottom: 5px; border-bottom: {s['bi']}px solid #333; padding-bottom: 2px;">[공급자]</div>
                        <div class="row"><div class="label">상호</div><div class="value stamp-box">{supplier.get('name','')} {stamp_html}</div></div>
                        <div class="row"><div class="label">사업자번호</div><div class="value">{supplier.get('biz_num','')}</div></div>
                        <div class="row"><div class="label">대표자</div><div class="value">{supplier.get('rep_name','')}</div></div>
                        <div class="row"><div class="label">주소</div><div class="value">{supplier.get('address','')}</div></div>
                        <div class="row"><div class="label">업태</div><div class="value">{supplier.get('cond','')}</div> <div class="label">종목</div><div class="value">{supplier.get('item','')}</div></div>
                    </div>
                </div>
                <div class="total-amount-section">
                    합계금액 (공급가액+세액): 일금 {korean_grand_total} 원정 (₩ {grand_total:,})
                </div>
                <table class="main-table">
                    <thead>
                        <tr>
                        <th width="{s["w_date"]}%">월일</th><th width="{s["w_item"]}%">품목</th><th width="{s["w_spec"]}%">규격</th><th width="{s["w_qty"]}%">수량</th>
                        {price_header}
                        <th width="{s["w_note"]}%">비고</th>
                        </tr>
                    </thead>
                    <tbody>
        """
        
        for item in items:
            price_cols = f"""<td class="right">{item.get('단가',0):,}</td><td class="right">{item.get('공급가액',0):,}</td><td class="right">{item.get('세액',0):,}</td>""" if not s['opt_hide_price'] else "<td></td><td></td><td></td>"
            page_html += f"""<tr><td class="center">{item.get('월일','')}</td><td>{item.get('품목','')}</td><td class="center">{item.get('규격','')}</td><td class="right">{item.get('수량',0):,}</td>{price_cols}<td>{item.get('비고','')}</td></tr>"""
        
        for _ in range(max(0, s['rows'] - len(items))):
            empty_price = "<td></td><td></td><td></td>" if not s['opt_hide_price'] else "<td></td><td></td><td></td>"
            page_html += f"<tr><td>&nbsp;</td><td></td><td></td><td></td>{empty_price}<td></td></tr>"
        
        total_qty = sum([x.get('수량',0) for x in items])
        sum_row = ""
        if not s['opt_hide_price']:
            sum_row = f"""<tr class="total-row"><td colspan="3" class="center">합 계</td><td class="right">{total_qty:,}</td><td class="right"></td><td class="right">{total_supply:,}</td><td class="right">{total_tax:,}</td><td></td></tr>
                        <tr class="total-row"><td colspan="3" class="center">총 합 계</td><td colspan="5" class="right" style="font-size: 14px;">₩ {grand_total:,}</td></tr>"""
        else:
            sum_row = f"""<tr class="total-row"><td colspan="3" class="center">합 계</td><td class="right">{total_qty:,}</td><td></td><td></td><td></td><td></td></tr>"""

        page_html += f"""</tbody><tfoot>{sum_row}</tfoot></table>
                <div style="margin-top: 5px; font-size: 12px;">{bank_info}</div>
                <div style="margin-top: 5px; font-size: 12px;">{s['opt_note']}</div>
                {sign_html}
            </div>
        """
        return page_html

    if s['opt_type'] == "공급받는자용":
        html = html_template + create_page("공급받는자용", False)
    elif s['opt_type'] == "공급자용":
        html = html_template + create_page("공급자용", True)
    elif s['opt_type'] == "표시 없음":
        html = html_template + create_page("", False)
    else: # 모두 인쇄
        html = html_template + create_page("공급받는자용", False)
        html += "<div class='page-break'></div>"
        html += create_page("공급자용", True)

    html += f"<!-- {uuid.uuid4()} -->"
    html += "</body></html>"
    st.components.v1.html(html, height=0, width=0)