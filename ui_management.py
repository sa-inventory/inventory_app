import streamlit as st
import pandas as pd
import datetime
import io
import uuid
from firebase_admin import firestore
from utils import get_common_codes, get_partners, is_basic_code_used, manage_code, manage_code_with_code, get_db, generate_report_html, search_address_api, validate_password

def render_shipping_operations(db, sub_menu):
    st.header("출고 작업")
    st.info("완성된 제품(봉제완료)을 출고 처리합니다.")
    
    if "ship_op_key" not in st.session_state:
        st.session_state["ship_op_key"] = 0

    shipping_partners = get_partners("배송업체")
    shipping_methods = get_common_codes("shipping_methods", ["택배", "화물", "용차", "직배송", "퀵서비스", "기타"])
    
    # [수정] 작업 모드 선택 (메뉴 통합)
    op_mode = st.radio("작업 모드", ["주문별 보기 (접수일순)", "제품별 보기 (재고순)"], horizontal=True)
    
    if op_mode == "주문별 보기 (접수일순)":
        st.subheader("주문별 출고 (발주번호 기준)")
        
        # [NEW] 검색 및 필터 UI
        with st.expander("검색", expanded=True):
            # [수정] 레이아웃 변경: 한 줄로 배치 및 날짜 입력 폭 축소
            c_f1, c_f2, c_f3 = st.columns([1.2, 1, 2])
            today = datetime.date.today()
            # [수정] 기간 검색 (접수일 기준) - 기본 3개월
            s_date_range = c_f1.date_input("접수일 기간", [today - datetime.timedelta(days=90), today], key="ship_ord_date_range")
            
            search_criteria = c_f2.selectbox("검색 기준", ["전체(통합)", "제품코드", "발주처", "제품명", "발주번호"], key="ship_ord_criteria")
            search_keyword = c_f3.text_input("검색어 입력", key="ship_ord_keyword")

        docs = db.collection("orders").where("status", "==", "봉제완료").stream()
        rows = []
        
        # 날짜 필터링 준비
        start_dt, end_dt = None, None
        if len(s_date_range) == 2:
            start_dt = datetime.datetime.combine(s_date_range[0], datetime.time.min)
            end_dt = datetime.datetime.combine(s_date_range[1], datetime.time.max)
        elif len(s_date_range) == 1:
            start_dt = datetime.datetime.combine(s_date_range[0], datetime.time.min)
            end_dt = datetime.datetime.combine(s_date_range[0], datetime.time.max)

        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            
            # 1. 날짜 필터 (접수일 기준)
            if start_dt and end_dt:
                d_date = d.get('date')
                if d_date:
                    if d_date.tzinfo: d_date = d_date.replace(tzinfo=None)
                    if not (start_dt <= d_date <= end_dt): continue
                else:
                    continue
            
            rows.append(d)
        rows.sort(key=lambda x: x.get('date', datetime.datetime.max))
        
        if rows:
            df = pd.DataFrame(rows)
            if 'date' in df.columns:
                df['date'] = df['date'].apply(lambda x: x.strftime('%Y-%m-%d') if not pd.isnull(x) and hasattr(x, 'strftime') else x)

            # 3. 키워드 검색 필터
            if search_keyword:
                search_keyword = search_keyword.lower()
                if search_criteria == "전체(통합)":
                     mask = df.apply(lambda x: search_keyword in str(x.get('product_code', '')).lower() or
                                              search_keyword in str(x.get('customer', '')).lower() or
                                              search_keyword in str(x.get('name', '')).lower() or
                                              search_keyword in str(x.get('order_no', '')).lower() or
                                              search_keyword in str(x.get('note', '')).lower(), axis=1)
                     df = df[mask]
                elif search_criteria == "제품코드":
                    df = df[df['product_code'].astype(str).str.lower().str.contains(search_keyword, na=False)]
                elif search_criteria == "발주처":
                    df = df[df['customer'].astype(str).str.lower().str.contains(search_keyword, na=False)]
                elif search_criteria == "제품명":
                    df = df[df['name'].astype(str).str.lower().str.contains(search_keyword, na=False)]
                elif search_criteria == "발주번호":
                    df = df[df['order_no'].astype(str).str.lower().str.contains(search_keyword, na=False)]

            # [NEW] 임의 등록 재고 발주번호 마스킹 (STOCK-으로 시작하면 -로 표시)
            if 'order_no' in df.columns:
                df['order_no'] = df['order_no'].apply(lambda x: '-' if str(x).startswith('STOCK-') else x)

            col_map = {
                "product_code": "제품코드", "order_no": "발주번호", "date": "접수일", 
                "customer": "발주처", "name": "제품명", "color": "색상", "weight": "중량(g)", "size": "사이즈", "stock": "수량",
                "delivery_to": "납품처", "delivery_contact": "연락처", "delivery_address": "주소", "note": "비고"
            }
            display_cols = ["product_code", "order_no", "date", "customer", "name", "color", "weight", "size", "stock", "delivery_to", "delivery_contact", "delivery_address", "note"]
            final_cols = [c for c in display_cols if c in df.columns]
            
            # [수정] 테이블 우측 상단에 '모든 품목 조회' 체크박스 배치
            c_h1, c_h2 = st.columns([6, 1])
            c_h1.write("🔽 출고할 항목을 선택(체크)하세요. (다중 선택 가능)")
            show_all_items = c_h2.checkbox("모든 품목 조회", value=False, help="체크하면 재고가 0인 품목도 표시됩니다.", key="ship_ord_show_all")
            
            # [수정] 재고 필터 적용 (기본: 재고 > 0)
            df['stock'] = pd.to_numeric(df['stock'], errors='coerce').fillna(0).astype(int)
            if not show_all_items:
                df = df[df['stock'] > 0]
            
            # [NEW] 동적 높이 계산 (행당 약 35px, 최대 20행 700px)
            table_height = min((len(df) + 1) * 35 + 3, 700)
            
            selection = st.dataframe(
                df[final_cols].rename(columns=col_map),
                width="stretch",
                hide_index=True,
                on_select="rerun",
                selection_mode="multi-row",
                height=table_height,
                key=f"ship_op_list_{st.session_state['ship_op_key']}"
            )
            
            if selection.selection.rows:
                selected_indices = selection.selection.rows
                selected_rows = df.iloc[selected_indices]
                
                st.divider()
                st.markdown(f"### 출고 정보 입력 (선택된 {len(selected_rows)}건)")
                
                # 제품 마스터에서 단가 정보 가져오기
                product_prices = {}
                try:
                    p_docs = db.collection("products").stream()
                    for p in p_docs:
                        product_prices[p.id] = p.to_dict().get("unit_price", 0)
                except: pass

                st.markdown("##### 배송 정보")
                c1, c2, c3 = st.columns(3)
                s_date = c1.date_input("출고일자", datetime.date.today())
                s_method = c2.selectbox("배송방법", shipping_methods)
                s_carrier = c3.selectbox("배송업체", ["직접입력"] + shipping_partners)
                if s_carrier == "직접입력":
                    s_carrier_input = c3.text_input("업체명 직접입력", placeholder="택배사/기사님 성함")
                    final_carrier = s_carrier_input
                else:
                    final_carrier = s_carrier
                
                st.markdown("##### 납품처 정보")
                first_row = selected_rows.iloc[0]
                c_d1, c_d2, c_d3 = st.columns(3)
                d_to = c_d1.text_input("납품처명", value=first_row.get('delivery_to', ''))
                d_contact = c_d2.text_input("납품연락처", value=first_row.get('delivery_contact', ''))
                d_addr = c_d3.text_input("납품주소", value=first_row.get('delivery_address', ''))
                s_note = st.text_area("비고 (송장번호/차량번호 등)", placeholder="예: 경동택배 123-456-7890")

                st.markdown("##### 수량 및 단가 확인")
                partial_ship = False
                ship_qty = 0
                current_stock = 0
                s_unit_price = 0
                
                if len(selected_rows) == 1:
                    current_stock = int(first_row.get('stock', 0))
                    p_code = first_row.get('product_code')
                    default_price = int(product_prices.get(p_code, 0))
                    
                    c_q1, c_q2 = st.columns(2)
                    # [FIX] current_stock이 0일 때 오류 방지
                    if current_stock > 0:
                        ship_qty = c_q1.number_input("출고 수량", min_value=1, max_value=current_stock, value=current_stock, step=10)
                    else:
                        ship_qty = c_q1.number_input("출고 수량", value=0, disabled=True)
                    
                    if current_stock > 0 and ship_qty < current_stock:
                        partial_ship = True
                        st.info(f"ℹ️ 부분 출고: {ship_qty}장 출고 후 {current_stock - ship_qty}장은 대기 목록에 남습니다.")
                    s_unit_price = c_q2.number_input("출고 단가 (원)", value=default_price, step=100)
                    calc_qty = ship_qty
                else:
                    total_qty = selected_rows['stock'].sum()
                    first_p_code = selected_rows.iloc[0].get('product_code')
                    default_price = int(product_prices.get(first_p_code, 0))
                    
                    c_q1, c_q2 = st.columns(2)
                    c_q1.text_input("총 출고 수량", value=f"{total_qty:,}장 (일괄 전량 출고)", disabled=True)
                    s_unit_price = c_q2.number_input("일괄 적용 단가 (원)", value=default_price, step=100)
                    ship_qty = total_qty
                    calc_qty = total_qty

                s_vat_inc = st.checkbox("단가에 부가세 포함", value=False)
                if s_vat_inc:
                    s_supply_price = int((calc_qty * s_unit_price) / 1.1)
                    s_vat = (calc_qty * s_unit_price) - s_supply_price
                    s_total_amount = calc_qty * s_unit_price
                else:
                    s_supply_price = calc_qty * s_unit_price
                    s_vat = int(s_supply_price * 0.1)
                    s_total_amount = s_supply_price + s_vat
                st.info(f"💰 **예상 금액**: 공급가액 {s_supply_price:,}원 + 부가세 {s_vat:,}원 = 합계 {s_total_amount:,}원")

                st.markdown("##### 운임비 설정 (선택)")
                c_cost1, c_cost2 = st.columns(2)
                s_cost = c_cost1.number_input("운임비 (원)", min_value=0, step=1000)
                s_cost_mode = c_cost2.radio("운임비 적용 방식", ["건당 운임비", "묶음 운임비(N분할)"], horizontal=True)

                if st.button("🚀 출고 처리", type="primary"):
                    total_items = len(selected_rows)
                    if total_items > 0 and s_cost > 0:
                        if s_cost_mode == "묶음 운임비(N분할)":
                            cost_per_item = int(s_cost / total_items)
                        else:
                            cost_per_item = s_cost
                    else:
                        cost_per_item = 0
                    
                    for idx, row in selected_rows.iterrows():
                        doc_id = row['id']
                        update_data = {
                            "status": "출고완료",
                            "shipping_date": datetime.datetime.combine(s_date, datetime.datetime.now().time()),
                            "shipping_method": s_method,
                            "shipping_carrier": final_carrier,
                            "shipping_cost": cost_per_item,
                            "shipping_unit_price": s_unit_price,
                            "vat_included": s_vat_inc,
                            "delivery_to": d_to,
                            "delivery_contact": d_contact,
                            "delivery_address": d_addr,
                            "note": s_note
                        }
                        if partial_ship and len(selected_rows) == 1:
                            doc_ref = db.collection("orders").document(doc_id)
                            org_data = doc_ref.get().to_dict()
                            new_ship_doc = org_data.copy()
                            new_ship_doc.update(update_data)
                            new_ship_doc['stock'] = ship_qty
                            new_ship_doc['parent_id'] = doc_id
                            db.collection("orders").add(new_ship_doc)
                            doc_ref.update({"stock": current_stock - ship_qty})
                        else:
                            db.collection("orders").document(doc_id).update(update_data)
                    
                    st.success(f"{len(selected_rows)}건 출고 처리 완료!")
                    st.session_state["ship_op_key"] += 1
                    st.rerun()
        else:
            st.info("출고 대기 중인 건이 없습니다.")

    else: # 제품별 보기 (재고순)
        st.subheader("제품별 일괄 출고")
        # 재고 현황 로직 재사용 (출고 기능 포함)
        render_inventory_logic(db, allow_shipping=True)

def render_shipping_status(db, sub_menu):
    st.header("출고 현황")
    st.info("출고된 내역을 조회하고 거래명세서를 발행합니다.")
    
    shipping_partners = get_partners("배송업체")
    
    # [NEW] 거래처 정보 미리 가져오기 (공급받는자 상세 표시용)
    partners_ref = db.collection("partners").stream()
    partners_map = {}
    for p in partners_ref:
        p_data = p.to_dict()
        partners_map[p_data.get('name')] = p_data

    if sub_menu == "출고 완료 내역 (조회/명세서)":
        st.subheader("출고 목록")
        
        if "key_ship_done" not in st.session_state:
            st.session_state["key_ship_done"] = 0

        # [수정] 검색 필터 UI 개선 (실시간 반영을 위해 form 제거 및 expander 활용)
        with st.expander("검색", expanded=True):
            c1, c2 = st.columns([2, 1])
            today = datetime.date.today()
            s_period = c1.date_input("조회 기간 (출고일)", [today - datetime.timedelta(days=30), today], key="ship_period")
            
            c3, c4, c5, c6 = st.columns(4)
            f_customer = c3.text_input("발주처", key="ship_f_cust")
            f_method = c4.multiselect("배송방법", ["택배", "화물", "용차", "직배송", "퀵서비스", "기타"], key="ship_f_method")
            f_carrier = c5.multiselect("배송업체", shipping_partners, key="ship_f_carrier")
            f_search = c6.text_input("통합 검색 (제품명/비고)", placeholder="검색어 입력", key="ship_f_search")

        # 데이터 로드 (기간 기준)
        start_dt = datetime.datetime.combine(s_period[0], datetime.time.min)
        end_dt = datetime.datetime.combine(s_period[1], datetime.time.max) if len(s_period) > 1 else datetime.datetime.combine(s_period[0], datetime.time.max)

        # '출고완료' 상태 조회 (기간 필터 적용)
        # Firestore 복합 인덱스 문제 회피를 위해 status로만 조회 후 메모리 필터링 권장 (데이터 양에 따라 조정)
        docs = db.collection("orders").where("status", "==", "출고완료").stream()
        rows = []
        for doc in docs:
            d = doc.to_dict()
            s_date = d.get('shipping_date')
            if s_date:
                if s_date.tzinfo: s_date = s_date.replace(tzinfo=None)
                if not (start_dt <= s_date <= end_dt): continue
            else:
                continue
            
            # [NEW] 메모리 필터링 적용
            if f_customer and f_customer not in d.get('customer', ''): continue
            if f_method and d.get('shipping_method') not in f_method: continue
            if f_carrier and d.get('shipping_carrier') not in f_carrier: continue
            if f_search:
                # 검색 대상 필드 통합
                search_target = f"{d.get('name','')} {d.get('note','')} {d.get('delivery_to','')} {d.get('order_no','')} {d.get('product_code','')}"
                if f_search not in search_target: continue

            d['id'] = doc.id
            rows.append(d)
            
        rows.sort(key=lambda x: x.get('shipping_date', datetime.datetime.min), reverse=True)
        
        if rows:
            df = pd.DataFrame(rows)
            if 'shipping_date' in df.columns:
                df['shipping_date'] = df['shipping_date'].apply(lambda x: x.strftime('%Y-%m-%d') if not pd.isnull(x) and hasattr(x, 'strftime') else x)

            # [FIX] 그룹화 및 계산에 필요한 컬럼 존재 여부 확인 및 초기화
            ensure_cols = ['stock', 'shipping_unit_price', 'shipping_cost', 'shipping_method', 'shipping_carrier', 'delivery_to', 'customer', 'name', 'order_no', 'color', 'weight', 'size']
            for c in ensure_cols:
                if c not in df.columns:
                    if c in ['stock', 'shipping_unit_price', 'shipping_cost', 'weight']:
                        df[c] = 0
                    else:
                        df[c] = ""
                elif c in ['stock', 'shipping_unit_price', 'shipping_cost', 'weight']:
                    df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0).astype(int)
                else:
                    df[c] = df[c].fillna("")

            # [NEW] 공급가액 계산 (단가 * 수량)
            df['supply_amount'] = df.apply(lambda x: int(x.get('stock', 0)) * int(x.get('shipping_unit_price', 0)), axis=1)

            # [NEW] 원본 발주번호(Base Order No) 추출 (예: 2405001-1 -> 2405001)
            # 문자열이 아니거나 '-'가 없으면 그대로 사용
            df['base_order_no'] = df['order_no'].apply(lambda x: str(x).split('-')[0] if isinstance(x, str) else str(x))

            col_map = {
                "shipping_date": "출고일", "customer": "발주처", "order_no": "발주번호", "name": "제품명", "color": "색상", "weight": "중량(g)", "size": "사이즈",
                "stock": "수량", "shipping_method": "배송방법", "shipping_carrier": "배송업체", "shipping_cost": "운임비",
                "stock": "수량", "shipping_unit_price": "단가", "supply_amount": "공급가액",
                "shipping_method": "배송방법", "shipping_carrier": "배송업체", "shipping_cost": "운임비",
                "delivery_to": "납품처", "delivery_contact": "납품연락처", "delivery_address": "납품주소", "note": "비고"
            }
            display_cols = ["shipping_date", "customer", "order_no", "name", "color", "weight", "size", "stock", "shipping_unit_price", "supply_amount", "shipping_method", "shipping_carrier", "shipping_cost", "delivery_to", "delivery_contact", "delivery_address", "note"]
            final_cols = [c for c in display_cols if c in df.columns]

            # [NEW] 묶어보기 토글
            view_grouped = st.checkbox("동일 출고건 묶어보기 (발주번호 기준)", help="체크하면 분할된 롤들을 원래 발주번호 기준으로 합쳐서 보여줍니다. (단, 출고일, 배송지, 단가가 모두 같아야 합쳐집니다)")
            
            if view_grouped:
                # 그룹화 기준: 원본발주번호 + 출고일 + 거래처 + 배송정보 + 단가
                # (단가가 다르면 합치지 않음, 배송방법이 다르면 합치지 않음)
                group_keys = ['base_order_no', 'shipping_date', 'customer', 'name', 'color', 'weight', 'size', 'shipping_unit_price', 'shipping_method', 'shipping_carrier', 'delivery_to']
                
                # 집계 함수 정의
                agg_funcs = {
                    'stock': 'sum',
                    'supply_amount': 'sum',
                    'shipping_cost': 'sum',
                    'id': list, # ID들을 리스트로 묶음 (취소 처리용)
                    'order_no': lambda x: f"{str(x.iloc[0]).split('-')[0]} (외 {len(x)-1}건)" if len(x) > 1 else str(x.iloc[0]), # 표시용 번호
                    'note': lambda x: ' / '.join(sorted(set([str(s) for s in x if s]))) # 비고 합치기
                }
                # 나머지 컬럼들은 첫 번째 값 사용
                for c in final_cols:
                    if c not in group_keys and c not in agg_funcs:
                        agg_funcs[c] = 'first'

                # 그룹화 실행
                df_display_source = df.groupby(group_keys, as_index=False).agg(agg_funcs)
                
                # 컬럼 순서 재정렬 (final_cols 기준)
                # order_no가 집계되면서 내용이 바뀌었으므로 display용으로 사용
                df_display = df_display_source[final_cols].rename(columns=col_map)
                
                # ID 리스트는 별도 보관 (선택 시 사용)
                df_display_ids = df_display_source['id'].tolist()
                
                st.info(f"💡 묶어보기 모드입니다. 총 **{len(df)}**건의 상세 내역이 **{len(df_display)}**건으로 요약되었습니다.")
            else:
                df_display = df[final_cols].rename(columns=col_map)
                df_display_ids = [[i] for i in df['id'].tolist()] # 1:1 매핑
                st.write(f"총 **{len(df)}**건의 출고 내역이 조회되었습니다.")

            st.write("🔽 목록에서 항목을 선택하여 거래명세서를 발행하거나 취소할 수 있습니다.")
            
            # [수정] 동적 키에 view_mode 반영하여 리셋 방지
            selection = st.dataframe(
                df_display,
                width="stretch",
                on_select="rerun",
                selection_mode="multi-row",
                key=f"ship_done_list_{st.session_state['key_ship_done']}_{view_grouped}"
            )
            
            # [NEW] 선택 항목 합계 표시
            if selection.selection.rows:
                sel_indices = selection.selection.rows
                # view_grouped 상태에 따라 참조하는 DF가 다름
                if view_grouped:
                    sel_rows = df_display_source.iloc[sel_indices]
                else:
                    sel_rows = df.iloc[sel_indices]
                    
                sum_qty = sel_rows['stock'].sum()
                sum_amt = sel_rows['supply_amount'].sum()
                sum_cost = sel_rows['shipping_cost'].sum()
                st.info(f"📊 선택 항목 합계: 수량 **{sum_qty:,}** / 공급가액 **{sum_amt:,}원** / 운임비 **{sum_cost:,}원**")
            
            st.divider()
            
            # [NEW] 기능 선택 (버튼식)
            action_mode = st.radio("작업 선택", ["목록 인쇄/엑셀", "거래명세서 발행", "출고 취소"], horizontal=True, label_visibility="collapsed")
            st.markdown("<div style='margin-bottom: 15px;'></div>", unsafe_allow_html=True)
            
            # 1. 목록 인쇄 및 엑셀 다운로드
            if action_mode == "목록 인쇄/엑셀":
                st.markdown("##### 현재 조회된 목록 내보내기")
                
                with st.expander("목록 인쇄 옵션"):
                    lp_c1, lp_c2, lp_c3, lp_c4 = st.columns(4)
                    lp_title = lp_c1.text_input("문서 제목", value="출고 목록", key="lp_title")
                    lp_title_size = lp_c2.number_input("제목 크기", value=24, step=1, key="lp_ts")
                    lp_body_size = lp_c3.number_input("본문 크기", value=10, step=1, key="lp_bs")
                    lp_padding = lp_c4.number_input("셀 여백", value=4, step=1, key="lp_pad")
                    
                    lp_c5, lp_c6, lp_c7, lp_c8 = st.columns(4)
                    lp_m_top = lp_c5.number_input("상단 여백", value=15, key="lp_mt")
                    lp_m_bottom = lp_c6.number_input("하단 여백", value=15, key="lp_mb")
                    lp_m_left = lp_c7.number_input("좌측 여백", value=15, key="lp_ml")
                    lp_m_right = lp_c8.number_input("우측 여백", value=15, key="lp_mr")
                    
                    lp_c9, lp_c10 = st.columns(2)
                    lp_bo = lp_c9.number_input("외곽선 굵기", value=1.0, step=0.1, format="%.1f", key="lp_bo")
                    lp_bi = lp_c10.number_input("안쪽선 굵기", value=0.5, step=0.1, format="%.1f", key="lp_bi")

                    lp_exclude_cols = st.multiselect("인쇄 제외 컬럼", list(col_map.values()), key="lp_exclude")

                lc1, lc2 = st.columns([1, 1])
                
                # 엑셀 다운로드
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    # [FIX] 화면에 보이는 그대로(그룹화 여부 반영) 엑셀 다운로드
                    df_display.to_excel(writer, index=False)
                lc1.download_button("💾 엑셀 다운로드", buffer.getvalue(), f"출고목록_{today}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                
                # 목록 인쇄
                if lc2.button("🖨️ 인쇄하기"):
                    print_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                    
                    # [수정] 선택된 항목이 있으면 해당 항목만, 없으면 전체 목록 인쇄
                    if selection.selection.rows:
                        target_df = df_display.iloc[selection.selection.rows] # 화면에 보이는 그대로 인쇄
                        print_title = f"{lp_title} (선택 항목)"
                    else:
                        target_df = df_display # 화면에 보이는 그대로 인쇄
                        print_title = lp_title

                    # 합계 계산
                    total_qty = target_df['stock'].sum() if 'stock' in target_df.columns else 0
                    total_amt = target_df['supply_amount'].sum() if 'supply_amount' in target_df.columns else 0
                    total_cost = target_df['shipping_cost'].sum() if 'shipping_cost' in target_df.columns else 0
                    
                    print_df = target_df # 이미 컬럼명 변경됨
                    
                    # 제외 컬럼 필터링
                    if lp_exclude_cols:
                        print_df = print_df.drop(columns=[c for c in lp_exclude_cols if c in print_df.columns])
                    
                    html = f"""
                    <html>
                    <head>
                        <title>{lp_title}</title>
                        <style>
                            @page {{ margin: {lp_m_top}mm 15mm {lp_m_bottom}mm 15mm; }}
                            @page {{ margin: {lp_m_top}mm {lp_m_right}mm {lp_m_bottom}mm {lp_m_left}mm; }}
                            body {{ font-family: 'Malgun Gothic', sans-serif; padding: 0; margin: 0; }}
                            h2 {{ text-align: center; margin-bottom: 5px; font-size: {lp_title_size}px; }}
                            .info {{ text-align: right; font-size: 10px; margin-bottom: 10px; color: #555; }}
                            table {{ width: 100%; border-collapse: collapse; font-size: {lp_body_size}px; margin-bottom: 10px; border: {lp_bo}px solid #444; }}
                            th, td {{ border: {lp_bi}px solid #444; padding: {lp_padding}px; text-align: center; }}
                            th {{ background-color: #f0f0f0; }}
                            .summary {{ text-align: right; font-weight: bold; font-size: {lp_body_size + 2}px; margin-top: 10px; border-top: 2px solid #444; padding-top: 5px; }}
                            @media screen {{ body {{ display: none; }} }}
                        </style>
                    </head>
                    <body onload="window.print()">
                        <h2>{lp_title}</h2>
                        <div class="info">출력일시: {print_now}</div>
                        {print_df.to_html(index=False)}
                        <div class="summary">
                            합계 - 수량: {total_qty:,} / 공급가액: {total_amt:,}원 / 운임비: {total_cost:,}원
                        </div>
                    </body>
                    </html>
                    """
                    st.components.v1.html(html, height=0, width=0)

            # 2. 거래명세서 발행 (기존 로직 이동)
            elif action_mode == "거래명세서 발행":
                if selection.selection.rows:
                    selected_indices = selection.selection.rows
                    
                    if view_grouped:
                        selected_rows = df_display_source.iloc[selected_indices]
                    else:
                        selected_rows = df.iloc[selected_indices]
                    
                    # 자사 정보 가져오기 (for defaults)
                    comp_doc = db.collection("settings").document("company_info").get()
                    comp_info = comp_doc.to_dict() if comp_doc.exists else {}

                    with st.expander("거래명세서 상세 설정", expanded=False):
                        # 1. 기본 설정
                        pc1, pc2 = st.columns(2)
                        print_type = pc1.radio("인쇄 종류", ["거래처용", "보관용", "거래처용 + 보관용"], index=2, horizontal=True, key="p_type")
                        p_show_vat = pc2.checkbox("부가세/공급가액 컬럼 표시", value=True, key="p_vat_col")
                        
                        # [NEW] 동일 품목 합산 옵션
                        p_merge_rows = pc2.checkbox("동일 품목/단가 합산 발행", value=True, help="체크하면 같은 제품, 같은 단가의 항목을 한 줄로 합쳐서 출력합니다.")

                        # 2. 표시 옵션
                        pc3, pc4, pc5, pc6 = st.columns(4)
                        p_hide_price = pc3.checkbox("단가/금액 숨김", value=False, key="p_hide_price")
                        p_show_sign = pc4.checkbox("인수자 서명란", value=True, key="p_show_sign")
                        p_show_approval = pc5.checkbox("결재란 표시", value=False, key="p_show_appr")
                        p_show_cust_info = pc6.checkbox("공급받는자 상세", value=False, key="p_show_cust_info")

                        # [NEW] 결재란 상세 설정 (최대 5명)
                        approval_names = []
                        if p_show_approval:
                            st.caption("결재란 직함 설정 (입력된 항목만 표시됩니다)")
                            ac1, ac2, ac3, ac4, ac5 = st.columns(5)
                            an1 = ac1.text_input("결재1", value="담 당", key="an1")
                            an2 = ac2.text_input("결재2", value="대 표", key="an2")
                            an3 = ac3.text_input("결재3", key="an3")
                            an4 = ac4.text_input("결재4", key="an4")
                            an5 = ac5.text_input("결재5", key="an5")
                            approval_names = [x for x in [an1, an2, an3, an4, an5] if x.strip()]
                            if not approval_names: approval_names = ["담 당", "대 표"]
                        
                        st.caption("페이지 여백 (mm)")
                        po_c8, po_c9, po_c10, po_c11 = st.columns(4)
                        p_m_top = po_c8.number_input("상단", value=15, step=1, key="p_mt")
                        p_m_bottom = po_c9.number_input("하단", value=15, step=1, key="p_mb")
                        p_m_left = po_c10.number_input("좌측", value=15, step=1, key="p_ml")
                        p_m_right = po_c11.number_input("우측", value=15, step=1, key="p_mr")
                        
                        po_c12, po_c13 = st.columns(2)
                        p_bo = po_c12.number_input("외곽선 굵기", value=1.0, step=0.1, format="%.1f", key="p_bo")
                        p_bi = po_c13.number_input("안쪽선 굵기", value=0.5, step=0.1, format="%.1f", key="p_bi")

                        # [NEW] 페이지당 행 수 설정 (자동/수동)
                        st.caption("레이아웃 조정")
                        p_rows_per_page = st.number_input("페이지당 최대 품목 수 (0=자동계산)", value=0, step=1, help="0으로 설정하면 여백과 글자 크기에 맞춰 자동으로 계산합니다. 인쇄 시 밀리면 이 값을 줄이세요.")

                        # 3. 텍스트 및 여백 설정
                        pc6, pc7, pc8, pc9 = st.columns(4)
                        p_title_text = pc6.text_input("문서 제목", value="거 래 명 세 서", key="p_title_txt")
                        p_issue_date = pc7.date_input("발행일자", datetime.date.today(), key="p_issue_date")
                        p_font_size = pc8.number_input("본문 글자 크기(px)", value=12, step=1, key="p_fs")
                        p_padding = pc9.number_input("셀 여백(px)", value=5, step=1, key="p_pad")

                        # 4. 문구 설정
                        print_bank = st.text_input("입금계좌 표시", value=f"{comp_info.get('bank_name', '')} {comp_info.get('bank_account', '')}", key="p_bank")
                        print_notes = st.text_area("하단 참고사항", value=comp_info.get('note', ''), height=60, key="p_notes")
                        print_remarks = st.text_area("전체 비고 (품목 하단)", help="품목 리스트 바로 아래에 표시될 내용입니다.", key="p_remarks")

                    if st.button("🖨️ 선택 항목 거래명세서 인쇄"):
                        # 자사 정보 가져오기
                        comp_doc = db.collection("settings").document("company_info").get()
                        comp_info = comp_doc.to_dict() if comp_doc.exists else {}
                        
                        # 선택된 항목을 거래처별로 그룹화
                        grouped = selected_rows.groupby('customer')
                        
                        pages_html = ""

                        # [NEW] 페이지당 행 수 계산 로직
                        def calculate_rows_per_page(options):
                            if options.get('rows_per_page', 0) > 0:
                                return options.get('rows_per_page')
                            
                            # A4 높이 297mm
                            # 여백 제외 가용 높이
                            avail_h = 297 - options.get('margin_top', 15) - options.get('margin_bottom', 15)
                            
                            # 헤더/푸터 높이 추정 (mm) - 레이아웃에 따라 조정
                            # 헤더(제목~결재란~공급자): 약 85mm
                            # 푸터(합계~비고~서명): 약 75mm
                            # 테이블 헤더: 약 10mm
                            fixed_h = 85 + 75 + 10
                            # [수정] 헤더/푸터 높이 동적 계산 (불필요한 여유 공간 제거)
                            # 헤더: 제목(10) + 날짜(5) + 공급자테이블(30) + 간격 + 발행일자추가 + 여유분 = 약 85mm (겹침 방지)
                            header_h = 85
                            # [수정] 헤더 높이 정밀 조정 (mm)
                            # 문서종류(3) + 제목(15) + 공급자정보(40) + 여유(5) = 약 63mm
                            header_h = 63
                            # 문서종류(3) + 제목(15) + 공급자정보(40) + 여유(2) = 약 60mm (기존 63mm에서 축소)
                            header_h = 60
                            if options.get('show_approval'):
                                header_h += 20 # 결재란 높이 추가
                            
                            # 푸터: 합계(8) + 비고(15) + 계좌(8) + 페이지(4) = 약 35mm
                            footer_h = 35
                            # [수정] 푸터 높이 정밀 조정 (mm)
                            # 합계(10) + 비고(25) + 계좌/참고(15) + 페이지(5) = 약 55mm
                            footer_h = 55
                            # 합계(10) + 비고(20) + 계좌/참고(10) + 페이지(5) = 약 45mm (기존 55mm에서 축소)
                            footer_h = 45
                            if options.get('show_sign'):
                                footer_h += 20 # 서명란 높이 추가
                                footer_h += 15 # 서명란 높이 추가
                                
                            table_header_h = 10
                            fixed_h = header_h + footer_h + table_header_h
                            table_h = avail_h - fixed_h
                            table_header_h = 12
                            
                            # [수정] 렌더링 오차 및 하단 여백 확보를 위해 안전 마진 증가 (약 1행 높이 추가)
                            # 기존 5mm -> 15mm로 넉넉하게 설정하여 겹침 방지
                            safety_margin = 15
                            # 기존 15mm -> 8mm로 조정하여 한 행 정도 더 표시되도록 수정
                            safety_margin = 8
                            # 기존 8mm -> 3mm로 과감하게 축소하여 행 추가 확보
                            safety_margin = 3
                            
                            # 행 높이 추정 (폰트크기 + 패딩*2 + 테두리)
                            # 1px ≈ 0.264mm. 줄간격 1.3배. 테두리 포함.
                            # 테이블 본문 가용 높이 (전체 - 헤더 - 푸터 - 안전여백)
                            max_table_body_h = avail_h - header_h - footer_h - table_header_h - safety_margin
                            
                            # 행 높이 계산 (폰트크기 + 패딩*2 + 테두리)
                            font_size = options.get('font_size', 12)
                            padding = options.get('padding', 5)
                            row_h = (font_size * 1.3 * 0.264) + (padding * 2 * 0.264) + 0.2
                            # 1px ≈ 0.264mm. 줄간격 1.4배. 테두리 포함.
                            row_h = (font_size * 1.4 * 0.264) + (padding * 2 * 0.264) + 0.5
                            
                            # [수정] 하단 여백을 채우기 위해 행 수 추가 (고정값 +6 대신 높이 기반 계산)
                            # 글자 크기가 커지면 행 높이(row_h)가 커져서 추가되는 행 수가 줄어듦 (겹침 방지)
                            # 약 38mm의 여유 공간을 채우는 방식으로 변경 (10pt 기준 6행 유지, 11pt 이상은 줄어듦)
                            extra_rows = int(38 / row_h)
                            return max(5, int(table_h / row_h) + extra_rows)
                            # 가용 높이에 들어갈 수 있는 행 수 계산 (내림)
                            # 공간이 좁아지거나 행이 커지면, 자동으로 행 개수(rows)가 줄어들어 침범을 방지함
                            rows = int(max_table_body_h / row_h)
                            
                            return max(5, rows)

                        def generate_invoice_pages(customer, group_df, page_type_str, comp_info, bank_info, notes_info, remarks_info, options, partners_map):
                            # 날짜
                            issue_date = options.get('issue_date', datetime.date.today())
                            print_date = issue_date.strftime("%Y-%m-%d")
                            bo = options.get('bo', 1.0)
                            bi = options.get('bi', 0.5)

                            # [수정] 표 스타일 통일 (행 높이 고정)
                            info_table_style = f"width:100%; height:100%; border-collapse:collapse; border:{bo}px solid #000; font-size:12px; table-layout:fixed;"
                            tr_style = "height: 25px;" # 행 높이 고정

                            # 공급자 정보 HTML
                            provider_html = f"""
                            <table style="{info_table_style}">
                                <colgroup>
                                    <col style="width: 25px;">
                                    <col style="width: 60px;">
                                    <col style="width: auto;">
                                    <col style="width: 60px;">
                                    <col style="width: auto;">
                                </colgroup>
                                <tr style="{tr_style}">
                                    <td rowspan="4" style="text-align:center; background:#f0f0f0; border:{bi}px solid #000;">공<br>급<br>자</td>
                                    <td style="border:{bi}px solid #000; padding:2px; background:#f0f0f0; text-align:center;">등록번호</td>
                                    <td colspan="3" style="border:{bi}px solid #000; padding:2px; text-align:center;">{comp_info.get('biz_num', '')}</td>
                                </tr>
                                <tr style="{tr_style}">
                                    <td style="border:{bi}px solid #000; padding:2px; background:#f0f0f0; text-align:center;">상호</td>
                                    <td style="border:{bi}px solid #000; padding:2px;">{comp_info.get('name', '')}</td>
                                    <td style="border:{bi}px solid #000; padding:2px; background:#f0f0f0; text-align:center;">성명</td>
                                    <td style="border:{bi}px solid #000; padding:2px;">{comp_info.get('rep_name', '')}</td>
                                </tr>
                                <tr style="{tr_style}">
                                    <td style="border:{bi}px solid #000; padding:2px; background:#f0f0f0; text-align:center;">주소</td>
                                    <td colspan="3" style="border:{bi}px solid #000; padding:2px;">{comp_info.get('address', '')}</td>
                                </tr>
                                <tr style="{tr_style}">
                                    <td style="border:{bi}px solid #000; padding:2px; background:#f0f0f0; text-align:center;">업태</td>
                                    <td style="border:{bi}px solid #000; padding:2px;">{comp_info.get('biz_type', '')}</td>
                                    <td style="border:{bi}px solid #000; padding:2px; background:#f0f0f0; text-align:center;">종목</td>
                                    <td style="border:{bi}px solid #000; padding:2px;">{comp_info.get('biz_item', '')}</td>
                                </tr>
                            </table>
                            """
                            
                            # [NEW] 공급받는자 정보 HTML (옵션에 따라 상세/단순 표시)
                            cust_info = partners_map.get(customer, {})
                            if options.get('show_cust_info') and cust_info:
                                customer_html = f"""
                                <table style="{info_table_style}">
                                    <colgroup>
                                        <col style="width: 25px;">
                                        <col style="width: 60px;">
                                        <col style="width: auto;">
                                        <col style="width: 60px;">
                                        <col style="width: auto;">
                                    </colgroup>
                                    <tr style="{tr_style}">
                                        <td rowspan="4" style="text-align:center; background:#f0f0f0; border:{bi}px solid #000;">공<br>급<br>받<br>는<br>자</td>
                                        <td style="border:{bi}px solid #000; padding:2px; background:#f0f0f0; text-align:center;">등록번호</td>
                                        <td colspan="3" style="border:{bi}px solid #000; padding:2px; text-align:center;">{cust_info.get('biz_num', '')}</td>
                                    </tr>
                                    <tr style="{tr_style}">
                                        <td style="border:{bi}px solid #000; padding:2px; background:#f0f0f0; text-align:center;">상호</td>
                                        <td style="border:{bi}px solid #000; padding:2px;">{cust_info.get('name', customer)}</td>
                                        <td style="border:{bi}px solid #000; padding:2px; background:#f0f0f0; text-align:center;">성명</td>
                                        <td style="border:{bi}px solid #000; padding:2px;">{cust_info.get('rep_name', '')}</td>
                                    </tr>
                                    <tr style="{tr_style}">
                                        <td style="border:{bi}px solid #000; padding:2px; background:#f0f0f0; text-align:center;">주소</td>
                                        <td colspan="3" style="border:{bi}px solid #000; padding:2px;">{cust_info.get('address', '')}</td>
                                    </tr>
                                    <tr style="{tr_style}">
                                        <td style="border:{bi}px solid #000; padding:2px; background:#f0f0f0; text-align:center;">업태</td>
                                        <td style="border:{bi}px solid #000; padding:2px;">{cust_info.get('item', '')}</td>
                                        <td style="border:{bi}px solid #000; padding:2px; background:#f0f0f0; text-align:center;">종목</td>
                                        <td style="border:{bi}px solid #000; padding:2px;"></td>
                                    </tr>
                                </table>
                                """
                            else:
                                customer_html = f"""
                                <table style="width:100%; height:100%; border-collapse:collapse; border:{bo}px solid #000;">
                                    <tr>
                                        <td style="border:{bi}px solid #000; padding:10px; text-align:center;">
                                            <span style="font-size:1.2em; font-weight:bold;">{customer}</span> 귀하<br><br>
                                        </td>
                                    </tr>
                                </table>
                                """

                            # [NEW] 결재란 HTML (사용자 설정 반영)
                            approval_html = ""
                            approvers = options.get('approval_names', [])
                            if options.get('show_approval') and approvers:
                                # 입력된 인원수만큼 셀 생성
                                cells_header = "".join([f'<td style="border:{bi}px solid #000; width:60px; padding:2px;">{name}</td>' for name in approvers])
                                cells_body = "".join([f'<td style="border:{bi}px solid #000; height:40px;"></td>' for _ in approvers])
                                
                                approval_html = f"""
                                <table style="border-collapse:collapse; border:{bo}px solid #000; font-size:11px; text-align:center; margin-left:auto; margin-bottom:5px;">
                                    <tr>
                                        <td rowspan="2" style="border:{bi}px solid #000; background:#f0f0f0; width:20px; padding:2px; vertical-align:middle;">결<br>재</td>
                                        {cells_header}
                                    </tr>
                                    <tr>
                                        {cells_body}
                                    </tr>
                                </table>
                                """

                            # [NEW] 페이지 분할 및 HTML 생성
                            rows_limit = calculate_rows_per_page(options)
                            total_items = len(group_df)
                            total_pages = (total_items + rows_limit - 1) // rows_limit if total_items > 0 else 1
                            
                            # 옵션 추출
                            hide_price = options.get('hide_price', False)
                            show_vat_col = options.get('show_vat_col', True)
                            cell_pad = options.get('padding', 5)

                            # 전체 합계 계산
                            grand_total_qty = group_df['stock'].sum()
                            grand_total_supply = 0
                            grand_total_vat = 0
                            
                            # 데이터 준비 (계산 미리 수행)
                            data_rows = []
                            for _, row in group_df.iterrows():
                                qty = int(row.get('stock', 0))
                                price = int(row.get('shipping_unit_price', 0))
                                vat_included = row.get('vat_included', False)

                                if vat_included:
                                    supply = int((qty * price) / 1.1)
                                    vat = (qty * price) - supply
                                else:
                                    supply = qty * price
                                    vat = int(supply * 0.1)
                                
                                grand_total_supply += supply
                                grand_total_vat += vat
                                
                                data_rows.append({
                                    'date': row.get('shipping_date', '')[5:],
                                    'name': row.get('name', ''),
                                    'size': row.get('size', ''),
                                    'qty': qty,
                                    'price': price,
                                    'supply': supply,
                                    'vat': vat,
                                    'note': row.get('note', ''),
                                    'base_order_no': row.get('base_order_no', '')
                                })
                            
                            # [NEW] 동일 품목 합산 로직
                            if options.get('merge_rows'):
                                merged_data = {}
                                for row in data_rows:
                                    # 키: 원본발주번호 + 제품명 + 규격 + 단가 + 비고 (비고가 다르면 합치지 않음)
                                    # [FIX] 다른 발주건끼리 합쳐지는 것을 방지하기 위해 base_order_no 포함
                                    key = (row['base_order_no'], row['name'], row['size'], row['price'], row['note'])
                                    if key not in merged_data:
                                        merged_data[key] = row.copy()
                                    else:
                                        merged_data[key]['qty'] += row['qty']
                                        merged_data[key]['supply'] += row['supply']
                                        merged_data[key]['vat'] += row['vat']
                                
                                # 딕셔너리를 다시 리스트로 변환 (날짜순 정렬 유지 노력)
                                # 여기서는 단순 변환
                                data_rows = list(merged_data.values())

                            # 전체 합계 재계산 (합산 과정에서 오차 보정 등은 생략, 단순 합계)
                            grand_total_amount = grand_total_supply + grand_total_vat

                            # [FIX] 변수 정의 (header_html, sign_html)
                            sign_html = ""
                            if options.get('show_sign'):
                                sign_html = f"""
                                <div style="margin-top:20px; text-align:right; font-size:{options.get('font_size')}px;">
                                    <strong>인수자 : ________________ (인)</strong>
                                </div>
                                """

                            header_html = f"""
                                <th style="border:{bi}px solid #000; padding:{cell_pad}px; width:8%;">월/일</th>
                                <th style="border:{bi}px solid #000; padding:{cell_pad}px; width:25%;">품목</th>
                                <th style="border:{bi}px solid #000; padding:{cell_pad}px; width:8%;">규격</th>
                                <th style="border:{bi}px solid #000; padding:{cell_pad}px; width:8%;">수량</th>
                            """
                            if not hide_price:
                                header_html += f'<th style="border:{bi}px solid #000; padding:{cell_pad}px; width:10%;">단가</th>'
                                if show_vat_col:
                                    header_html += f"""
                                    <th style="border:{bi}px solid #000; padding:{cell_pad}px; width:12%;">공급가액</th>
                                    <th style="border:{bi}px solid #000; padding:{cell_pad}px; width:12%;">세액</th>
                                    """
                                else:
                                    header_html += f'<th style="border:{bi}px solid #000; padding:{cell_pad}px; width:15%;">금액</th>'
                            header_html += f'<th style="border:{bi}px solid #000; padding:{cell_pad}px; width:auto;">비고</th>'

                            # 페이지별 HTML 생성
                            pages_output = ""
                            
                            for page_num in range(total_pages):
                                start_idx = page_num * rows_limit
                                end_idx = start_idx + rows_limit
                                page_rows = data_rows[start_idx:end_idx]
                                is_last_page = (page_num == total_pages - 1)
                                
                                items_html = ""
                                for row in page_rows:
                                    items_html += f"""
                                <tr>
                                    <td style="border:{bi}px solid #000; padding:{cell_pad}px; text-align:center;">{row['date']}</td>
                                    <td style="border:{bi}px solid #000; padding:{cell_pad}px;">{row['name']}</td>
                                    <td style="border:{bi}px solid #000; padding:{cell_pad}px; text-align:center;">{row['size']}</td>
                                    <td style="border:{bi}px solid #000; padding:{cell_pad}px; text-align:right;">{row['qty']:,}</td>
                                """
                                    if not hide_price:
                                        items_html += f'<td style="border:{bi}px solid #000; padding:{cell_pad}px; text-align:right;">{row["price"]:,}</td>'
                                        if show_vat_col:
                                            items_html += f"""
                                            <td style="border:{bi}px solid #000; padding:{cell_pad}px; text-align:right;">{row["supply"]:,}</td>
                                            <td style="border:{bi}px solid #000; padding:{cell_pad}px; text-align:right;">{row["vat"]:,}</td>
                                            """
                                        else:
                                            items_html += f'<td style="border:{bi}px solid #000; padding:{cell_pad}px; text-align:right;">{row["supply"]+row["vat"]:,}</td>'
                                    
                                    items_html += f'<td style="border:{bi}px solid #000; padding:{cell_pad}px;">{row["note"]}</td></tr>'

                                # 빈 줄 채우기
                                col_span = 4
                                if not hide_price:
                                    col_span += 1
                                    if show_vat_col: col_span += 2
                                    else: col_span += 1
                                col_span += 1
                                
                                empty_td = f'<td style="border:{bi}px solid #000; padding:{cell_pad}px;">&nbsp;</td>'
                                empty_row = f'<tr>' + (empty_td * col_span) + '</tr>'
                                
                                for _ in range(rows_limit - len(page_rows)):
                                    items_html += empty_row

                                # 합계 행 (마지막 페이지에만 표시)
                                footer_html = ""
                                if is_last_page:
                                    footer_html = f"""
                                        <tr style="font-weight:bold; background-color:#f9f9f9;">
                                            <td colspan="3" style="border:{bi}px solid #000; padding:{cell_pad}px;">합 계</td>
                                            <td style="border:{bi}px solid #000; padding:{cell_pad}px; text-align:right;">{grand_total_qty:,}</td>
                                    """
                                    if not hide_price:
                                        footer_html += f'<td style="border:{bi}px solid #000; padding:{cell_pad}px;"></td>'
                                        if show_vat_col:
                                            footer_html += f"""
                                            <td style="border:{bi}px solid #000; padding:{cell_pad}px; text-align:right;">{grand_total_supply:,}</td>
                                            <td style="border:{bi}px solid #000; padding:{cell_pad}px; text-align:right;">{grand_total_vat:,}</td>
                                            """
                                        else:
                                            footer_html += f'<td style="border:{bi}px solid #000; padding:{cell_pad}px; text-align:right;">{grand_total_amount:,}</td>'
                                    footer_html += f'<td style="border:{bi}px solid #000; padding:{cell_pad}px;"></td></tr>'

                                # 페이지 HTML 조립
                                # [수정] 페이지 높이를 여백 제외한 크기로로
                                page_h_mm = 297 - options.get('margin_top', 15) - options.get('margin_bottom', 15)
                                
                                page_html = f"""
                            <div class="page" style="page-break-after: always; padding: 0; border: none; margin: 0 auto; width: 100%; height: {page_h_mm}mm; box-sizing: border-box; position: relative;">
                                <div class="content-wrap">
                                <div style="text-align:left; font-size:10px; margin-bottom:2px;">[{page_type_str}]</div>
                                <h1 style="text-align:center; letter-spacing:10px; margin-bottom:10px; margin-top:0;">{options.get('title_text')}</h1>
                                {approval_html}
                                <div style="display:flex; justify-content:space-between; margin-bottom:20px;">
                                    <div style="width:48%;">
                                        <div style="text-align:left; font-size:12px; margin-bottom:5px; font-weight:bold;">발행일자 : {print_date}</div>
                                        {customer_html}
                                    </div>
                                    <div style="width:48%;">
                                        <div style="text-align:left; font-size:12px; margin-bottom:5px; font-weight:bold; visibility:hidden;">발행일자 : {print_date}</div>
                                        {provider_html}
                                    </div>
                                </div>
                                
                                <table style="width:100%; border-collapse:collapse; border:{bo}px solid #000; font-size:{options.get('font_size')}px; text-align:center;">
                                    <tr style="background-color:#f0f0f0;">
                                        {header_html}
                                    </tr>
                                    {items_html}
                                    {footer_html}
                                </table>
                                </div>
                                
                                <div class="footer-wrap" style="position: absolute; bottom: 0; width: 100%;">
                                    {f'''<div style="margin-top:5px; font-size:{options.get('font_size')}px; border: {bo}px solid #000; padding: 5px;">
                                        <strong>합계금액 : {grand_total_amount:,} 원{ " (부가세포함)" if not show_vat_col else "" }</strong>
                                    </div>''' if not hide_price and is_last_page else ''}

                                    <div style="margin-top:5px; font-size:{options.get('font_size')}px; border: {bo}px solid #000; min-height: 50px; position: relative; text-align: left;">
                                        <span style="position: absolute; top: 5px; left: 5px; font-weight: bold;">[전체 비고]</span>
                                        <div style="padding: 25px 5px 5px 5px; white-space: pre-wrap;">{remarks_info}</div>
                                    </div>
                                    
                                    <div style="margin-top:5px; font-size:{options.get('font_size')}px;">
                                        <strong>[입금계좌]</strong> {bank_info} <br>
                                        <strong>[참고사항]</strong> {notes_info}
                                    </div>
                                    {sign_html}
                                    <div style="text-align:center; font-size:10px; margin-top:5px;">{page_num + 1} / {total_pages}</div>
                                </div>
                            </div>
                            """
                                pages_output += page_html
                            
                            return pages_output
                        
                        # 옵션 딕셔너리 생성
                        print_opts = {
                            'title_text': p_title_text,
                            'font_size': p_font_size,
                            'padding': p_padding,
                            'hide_price': p_hide_price,
                            'show_vat_col': p_show_vat,
                            'show_sign': p_show_sign,
                            'show_approval': p_show_approval,
                            'approval_names': approval_names,
                            'show_cust_info': p_show_cust_info,
                            'merge_rows': p_merge_rows, # [NEW] 합산 옵션 전달
                            'bo': p_bo,
                            'bi': p_bi
                        }

                        for customer, group in grouped:
                            if print_type == "거래처용":
                                pages_html += generate_invoice_pages(customer, group, "거래처용", comp_info, print_bank, print_notes, print_remarks, print_opts, partners_map)
                            elif print_type == "보관용":
                                pages_html += generate_invoice_pages(customer, group, "보관용", comp_info, print_bank, print_notes, print_remarks, print_opts, partners_map)
                            else: # 둘 다
                                pages_html += generate_invoice_pages(customer, group, "거래처용", comp_info, print_bank, print_notes, print_remarks, print_opts, partners_map)
                                pages_html += generate_invoice_pages(customer, group, "보관용", comp_info, print_bank, print_notes, print_remarks, print_opts, partners_map)
                        
                        full_html = f"""
                        <html>
                        <head>
                            <title>거래명세서 인쇄</title>
                            <style>
                                @page {{ margin: {p_m_top}mm {p_m_right}mm {p_m_bottom}mm {p_m_left}mm; }}
                                body {{ font-family: 'Malgun Gothic', sans-serif; }}
                                @media print {{ 
                                    .page {{ border: none !important; margin: 0 !important; }} 
                                    body {{ margin: 0; padding: 0; }}
                                }}
                            </style>
                        </head>
                        <body onload="window.print()">
                            {pages_html}
                        </body>
                        </html>
                        """
                        st.components.v1.html(full_html, height=0, width=0)
                else:
                    st.info("거래명세서를 발행할 항목을 선택하세요.")

            # 3. 출고 취소 (기존 로직 이동)
            elif action_mode == "출고 취소":
                if selection.selection.rows:
                    selected_indices = selection.selection.rows
                    
                    # [수정] 취소 대상 ID 목록 확보
                    target_ids = []
                    if view_grouped:
                        # 그룹화된 행의 'id' 컬럼은 리스트 형태임
                        sel_rows = df_display_source.iloc[selected_indices]
                        for ids in sel_rows['id']:
                            target_ids.extend(ids)
                    else:
                        sel_rows = df.iloc[selected_indices]
                        target_ids = sel_rows['id'].tolist()
                    
                    if st.button("선택 항목 출고 취소", type="primary"):
                        for doc_id in target_ids:
                            db.collection("orders").document(doc_id).update({"status": "봉제완료"})
                        st.success(f"총 {len(target_ids)}건의 출고가 취소되었습니다.")
                        st.session_state["key_ship_done"] += 1
                        st.rerun()
                else:
                    st.info("취소할 항목을 선택하세요.")
        else:
            st.info("출고 완료된 내역이 없습니다.")

    elif sub_menu == "배송/운임 통계":
        st.subheader("📊 배송/운임 통계")
        st.info("기간별, 배송업체별 운임비 지출 현황을 확인합니다.")
        
        with st.form("ship_stats_form"):
            # [수정] 통계 기준 선택 (기간별/월별/년도별)
            stat_type = st.radio("통계 기준", ["기간별(일자)", "월별", "년도별"], horizontal=True)
            
            c1, c2, c3 = st.columns(3)
            
            if stat_type == "기간별(일자)":
                today = datetime.date.today()
                stats_date = c1.date_input("조회 기간", [today - datetime.timedelta(days=30), today])
            elif stat_type == "월별":
                this_year = datetime.date.today().year
                stats_year = c1.number_input("조회 년도", value=this_year, step=1, format="%d")
            else: # 년도별
                c1.write("최근 데이터 기준")

            stats_carrier = c2.selectbox("배송업체 필터", ["전체"] + shipping_partners)
            stats_customer = c3.text_input("발주처 필터")
            
            st.form_submit_button("통계 조회")
            
        # 데이터 조회 및 필터링
        docs = db.collection("orders").where("status", "==", "출고완료").stream()
        rows = []
        for doc in docs:
            d = doc.to_dict()
            s_date = d.get('shipping_date')
            
            if s_date:
                if s_date.tzinfo: s_date = s_date.replace(tzinfo=None)
                
                # 날짜 필터링
                if stat_type == "기간별(일자)" and isinstance(stats_date, list) and len(stats_date) == 2:
                    start_dt = datetime.datetime.combine(stats_date[0], datetime.time.min)
                    end_dt = datetime.datetime.combine(stats_date[1], datetime.time.max)
                    if start_dt <= s_date <= end_dt:
                        rows.append(d)
                elif stat_type == "월별":
                    if s_date.year == stats_year:
                        rows.append(d)
                else: # 년도별 (전체)
                    rows.append(d)

            if rows:
                df_stats = pd.DataFrame(rows)
                # 운임비 합계
                total_cost = df_stats['shipping_cost'].sum() if 'shipping_cost' in df_stats.columns else 0
                total_count = len(df_stats)
                
                st.metric("총 운임비 지출", f"{total_cost:,}원", f"총 {total_count}건")

                # 추가 필터링 (업체/거래처) - 메모리 상에서 처리
                if stats_carrier != "전체":
                    df_stats = df_stats[df_stats['shipping_carrier'] == stats_carrier]
                if stats_customer:
                    df_stats = df_stats[df_stats['customer'].str.contains(stats_customer, na=False)]
                
                st.divider()
                
                # 통계 그룹화 기준 설정
                if stat_type == "기간별(일자)":
                    df_stats['group_key'] = df_stats['shipping_date'].apply(lambda x: x.strftime('%Y-%m-%d'))
                    group_label = "일자"
                elif stat_type == "월별":
                    df_stats['group_key'] = df_stats['shipping_date'].apply(lambda x: x.strftime('%Y-%m'))
                    group_label = "월"
                else:
                    df_stats['group_key'] = df_stats['shipping_date'].apply(lambda x: x.strftime('%Y'))
                    group_label = "년도"

                c_chart1, c_chart2 = st.columns(2)
                
                # 1. 시계열 추이 (운임비)
                with c_chart1:
                    st.markdown(f"##### {group_label}별 운임비 추이")
                    time_stats = df_stats.groupby('group_key')['shipping_cost'].sum().reset_index()
                    time_stats.columns = [group_label, '운임비']
                    st.bar_chart(time_stats.set_index(group_label))

                # 2. 배송업체별 점유율
                with c_chart2:
                    st.markdown("##### 배송업체별 운임비 비중")
                    if 'shipping_carrier' in df_stats.columns:
                        carrier_pie = df_stats.groupby('shipping_carrier')['shipping_cost'].sum()
                        st.bar_chart(carrier_pie) # Streamlit 기본 차트 사용

                # 3. 상세 테이블 (업체별)
                if 'shipping_carrier' in df_stats.columns and 'shipping_cost' in df_stats.columns:
                    st.markdown("##### 업체별 상세 지출 현황")
                    carrier_stats = df_stats.groupby(['shipping_carrier', 'customer'])['shipping_cost'].sum().reset_index()
                    # [수정] 컬럼 수 불일치 오류 해결 (3개 컬럼)
                    carrier_stats.columns = ['배송업체', '발주처', '운임비 합계']
                    carrier_stats = carrier_stats.sort_values('운임비 합계', ascending=False)
                    st.dataframe(carrier_stats, width="stretch", hide_index=True)
                    
                    st.bar_chart(carrier_stats.set_index('배송업체'))
            else:
                st.info("조회된 배송 내역이 없습니다.")

# [NEW] 재고 현황 로직을 별도 함수로 분리 (출고 작업과 재고 현황에서 공유)
def render_inventory_logic(db, allow_shipping=False):
    # [NEW] 파트너 권한 확인
    user_role = st.session_state.get("role")
    linked_partner = st.session_state.get("linked_partner")
    is_partner = (user_role == "partner")

    # [NEW] 스마트 데이터 에디터 - 1. 변경사항 검토 및 확정 UI
    changes_key = f'inventory_changes_{allow_shipping}'
    if st.session_state.get(changes_key):
        changes = st.session_state[changes_key]
        st.divider()
        st.subheader("📝 변경사항 검토")
        st.warning("아래 변경사항을 확인하고 확정 버튼을 눌러주세요.")
        st.warning("변경된 셀은 노란색으로 표시됩니다. 내용을 확인하고 확정 버튼을 눌러주세요.")
        
        for change in changes:
            st.markdown(f"**- 제품명: {change['name']}** (ID: `{change['id']}`)")
            change_details = change['changes']
            if 'stock' in change_details:
                before, after = change_details['stock']
                st.markdown(f"  - **재고수량**: `{before:,}` → `{after:,}`")
            if 'shipping_unit_price' in change_details:
                before, after = change_details['shipping_unit_price']
                st.markdown(f"  - **단가**: `{before:,}` → `{after:,}`")
        # [NEW] 변경 내역 DataFrame 생성 및 스타일링
        display_rows = []
        for c in changes:
            # row_data가 없으면(구버전 세션 등) 기본값 처리
            row = c.get('row_data', {'제품명': c['name'], '구분/발주처': '-', '재고수량': 0, '단가': 0}).copy()
            row['_id'] = c['id']
            display_rows.append(row)
            
        if display_rows:
            df_review = pd.DataFrame(display_rows)
            
            def highlight_changes(row):
                styles = [''] * len(row)
                c_info = next((x for x in changes if x['id'] == row['_id']), None)
                if c_info:
                    changed_fields = c_info['changes']
                    # 필드명과 컬럼명 매핑
                    field_map = {'stock': '재고수량', 'shipping_unit_price': '단가'}
                    
                    for field, col_name in field_map.items():
                        if field in changed_fields:
                            try:
                                idx = row.index.get_loc(col_name)
                                styles[idx] = 'background-color: #fff3cd; color: #856404; font-weight: bold;'
                            except: pass
                return styles

            st.dataframe(
                df_review.drop(columns=['_id']).style.apply(highlight_changes, axis=1),
                hide_index=True,
                use_container_width=True
            )
        
        c1, c2, c3 = st.columns([1.2, 1, 5])
        if c1.button("✅ 변경 확정", type="primary", key=f"confirm_inv_changes_{allow_shipping}"):
            # Firestore에 변경사항 업데이트
            for change in changes:
                doc_id = change['id']
                update_data = {}
                if 'stock' in change['changes']:
                    update_data['stock'] = change['changes']['stock'][1]
                if 'shipping_unit_price' in change['changes']:
                    update_data['shipping_unit_price'] = change['changes']['shipping_unit_price'][1]
                
                if update_data:
                    db.collection("orders").document(doc_id).update(update_data)
            
            st.success(f"{len(changes)}건의 재고 정보가 수정되었습니다.")
            del st.session_state[changes_key]
            st.rerun()
            
        if c2.button("❌ 취소", key=f"cancel_inv_changes_{allow_shipping}"):
            del st.session_state[changes_key]
            st.rerun()
        
        st.stop() # 검토 중에는 아래 UI를 그리지 않음

    # 재고 기준: status == "봉제완료" (출고 전 단계)
    docs = db.collection("orders").where("status", "==", "봉제완료").stream()
    rows = []
    for doc in docs:
        d = doc.to_dict()
        
        # [NEW] 파트너인 경우 본인 데이터만 필터링
        if is_partner and linked_partner:
            if d.get("customer") != linked_partner: continue
            
        d['id'] = doc.id
        rows.append(d)

    if rows:
        df = pd.DataFrame(rows)
        
        # 상단: 제품별 재고 요약
        st.subheader("제품별 재고")
        
        ensure_cols = ['product_code', 'name', 'product_type', 'yarn_type', 'weight', 'size', 'stock', 'shipping_unit_price']
        for c in ensure_cols:
            if c not in df.columns:
                if c in ['stock', 'weight', 'shipping_unit_price']:
                    df[c] = 0
                else:
                    df[c] = ""
        
        df['stock'] = pd.to_numeric(df['stock'], errors='coerce').fillna(0).astype(int)
        df['weight'] = pd.to_numeric(df['weight'], errors='coerce').fillna(0).astype(int)
        df['shipping_unit_price'] = pd.to_numeric(df['shipping_unit_price'], errors='coerce').fillna(0).astype(int)

        # [NEW] 총 재고 금액 계산
        df['total_value'] = df['stock'] * df['shipping_unit_price']

        # [NEW] 간편 검색 기능 (사용자 요청 반영)
        with st.expander("검색", expanded=True):
            c_search1, c_search2 = st.columns([1, 3])
            search_criteria = c_search1.selectbox("검색 기준", ["전체(통합)", "제품코드", "발주처", "제품종류", "제품명"], key=f"inv_search_criteria_{allow_shipping}")
            search_keyword = c_search2.text_input("검색어 입력", key=f"inv_search_keyword_{allow_shipping}")
            
            if search_keyword:
                search_keyword = search_keyword.lower()
                if search_criteria == "전체(통합)":
                    mask = df.apply(lambda x: search_keyword in str(x.get('product_code', '')).lower() or
                                              search_keyword in str(x.get('customer', '')).lower() or
                                              search_keyword in str(x.get('product_type', '')).lower() or
                                              search_keyword in str(x.get('name', '')).lower() or
                                              search_keyword in str(x.get('note', '')).lower() or
                                              search_keyword in str(x.get('order_no', '')).lower(), axis=1)
                    df = df[mask]
                elif search_criteria == "제품코드":
                    df = df[df['product_code'].astype(str).str.lower().str.contains(search_keyword, na=False)]
                elif search_criteria == "발주처":
                    df = df[df['customer'].astype(str).str.lower().str.contains(search_keyword, na=False)]
                elif search_criteria == "제품종류":
                    df = df[df['product_type'].astype(str).str.lower().str.contains(search_keyword, na=False)]
                elif search_criteria == "제품명":
                    df = df[df['name'].astype(str).str.lower().str.contains(search_keyword, na=False)]

        # [NEW] 기본 정렬 설정: 제품코드(오름차순) -> 제품명(오름차순)
        sort_cols = []
        if 'product_code' in df.columns: sort_cols.append('product_code')
        if 'name' in df.columns: sort_cols.append('name')
        if sort_cols:
            df = df.sort_values(by=sort_cols, ascending=[True] * len(sort_cols))
        
        # [NEW] 조회 방식 선택 (요약 vs 전체 리스트)
        if is_partner:
            view_mode = "제품명 보기(제품코드별 상세품목)"
        else:
            # [수정] 버튼 토글 방식으로 변경 (사용자 요청 반영)
            vm_key = f"view_mode_state_{allow_shipping}"
            if vm_key not in st.session_state:
                st.session_state[vm_key] = "제품코드 보기"

            # 버튼 배치를 위한 컬럼 설정
            c_vm1, c_vm2, c_dummy = st.columns([1.5, 1.5, 7])
            
            # 현재 상태 확인
            current_mode = st.session_state[vm_key]
            
            # 제품코드 보기 버튼
            with c_vm1:
                if st.button("제품코드 보기", 
                             type="primary" if current_mode == "제품코드 보기" else "secondary", 
                             use_container_width=True, 
                             key=f"btn_vm_code_{allow_shipping}"):
                    st.session_state[vm_key] = "제품코드 보기"
                    st.rerun()
            
            # 제품명 보기 버튼
            with c_vm2:
                if st.button("제품명 보기(상세)", 
                             type="primary" if current_mode == "제품명 보기(제품코드별 상세품목)" else "secondary", 
                             use_container_width=True, 
                             help="제품코드별 상세 품목 리스트를 확인합니다.",
                             key=f"btn_vm_name_{allow_shipping}"):
                    st.session_state[vm_key] = "제품명 보기(제품코드별 상세품목)"
                    st.rerun()
            
            view_mode = st.session_state[vm_key]

        # [NEW] 테이블 우측 상단에 '모든 품목 조회' 체크박스 배치
        # [수정] 라디오버튼을 우측 끝으로 붙이기 위해 비율 조정 (좌측 텍스트영역 확보, 우측 라디오버튼 영역 최소화)
        c_h1, c_h2 = st.columns([7.5, 2.5])
        with c_h1:
            if view_mode == "제품코드 보기":
                 st.write("🔽 상세 내역을 확인할 제품을 선택하세요.")
            else:
                 st.write("🔽 전체 재고 내역입니다.")
             
        # [수정] 재고 필터: 라디오 버튼 (전체코드보기 / 재고있는 품목보기)
        with c_h2:
            stock_filter_opt = st.radio("조회 옵션", ["전체코드보기", "재고있는 품목보기"], index=0, horizontal=True, label_visibility="collapsed", key=f"inv_stock_filter_{allow_shipping}")

        # [NEW] 재고 필터 적용 (기본: 재고 > 0)
        if stock_filter_opt == "재고있는 품목보기":
            df = df[df['stock'] > 0]

        # [MOVED] 요약 데이터 계산 (필터링 후)
        summary = df.groupby('product_code').agg({
            'product_type': 'first',
            'yarn_type': 'first',
            'weight': 'first',
            'size': 'first',
            'stock': 'sum',
            'shipping_unit_price': 'mean',
            'total_value': 'sum'
        }).reset_index()
        
        summary['shipping_unit_price'] = summary['shipping_unit_price'].astype(int)
        
        summary_cols = {
            'product_code': '제품코드', 'product_type': '제품종류',
            'yarn_type': '사종', 'weight': '중량', 'size': '사이즈',
            'stock': '재고수량', 'shipping_unit_price': '평균단가',
            'total_value': '총재고금액'
        }
        
        disp_cols = ['product_code', 'product_type', 'yarn_type', 'weight', 'size', 'shipping_unit_price', 'stock', 'total_value']

        # [MOVED] 인쇄 및 엑셀 내보내기 설정 (공통 영역으로 이동)
        # 데이터 준비 (공통)
        df_detail_print = df.copy()
        if 'date' in df_detail_print.columns:
            df_detail_print['date'] = df_detail_print['date'].apply(lambda x: x.strftime('%Y-%m-%d') if not pd.isnull(x) and hasattr(x, 'strftime') else str(x)[:10])
        
        # 상세 내역에 표시할 컬럼 정의 (모든 컬럼 포함)
        detail_col_map = {
            "product_code": "제품코드", "customer": "구분/발주처", "name": "제품명", 
            "product_type": "제품종류", "yarn_type": "사종", "weight": "중량", 
            "size": "사이즈", "color": "색상", "shipping_unit_price": "단가", 
            "stock": "재고수량", "order_no": "발주번호", "date": "등록/접수일", "note": "비고",
            "delivery_req_date": "납품요청일", "delivery_to": "납품처"
        }
        detail_cols = [c for c in detail_col_map.keys() if c in df_detail_print.columns]
        df_detail_final = df_detail_print[detail_cols].rename(columns=detail_col_map)

        # [수정] 구분선 간격 조정 (좁게)
        st.markdown("<hr style='margin: 10px 0; border: none; border-top: 1px solid #e6e6e6;'>", unsafe_allow_html=True)

        # [NEW] 선택된 행을 저장할 변수 (출고용)
        selected_rows_for_shipping = None

        # [NEW] 스마트 데이터 에디터 - 2. 수정 모드 토글
        is_admin = st.session_state.get("role") == "admin"
        can_edit = is_admin and not allow_shipping
        edit_mode = False
        if can_edit:
            edit_mode = st.toggle("재고 수정 모드 (수량/단가)", key=f"edit_mode_{allow_shipping}")

        # 관리자 권한 확인 (삭제 기능용)
        is_admin = st.session_state.get("role") == "admin"

        if view_mode == "제품코드 보기":
            # [수정] 동적 높이 계산 (행당 약 35px, 최대 20행 700px)
            summary_height = min((len(summary) + 1) * 35 + 3, 700)
            
            selection_summary = st.dataframe(
                summary[disp_cols].rename(columns=summary_cols),
                width="stretch",
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                height=summary_height,
                key=f"inv_summary_list_{allow_shipping}"
            )
            
            # [NEW] 제품별 요약 목록 합계 표시
            st.markdown(f"<div style='text-align:right; font-weight:bold; padding:5px; color:#333;'>총 재고수량 합계: {summary['stock'].sum():,}</div>", unsafe_allow_html=True)

            if selection_summary.selection.rows:
                idx = selection_summary.selection.rows[0]
                sel_p_code = summary.iloc[idx]['product_code']
                
                st.divider()
                st.markdown(f"### 상세 재고 내역: **{sel_p_code}**")
                
                detail_df = df[df['product_code'] == sel_p_code].copy()
                
                if 'date' in detail_df.columns:
                    detail_df['date'] = detail_df['date'].apply(lambda x: x.strftime('%Y-%m-%d') if not pd.isnull(x) and hasattr(x, 'strftime') else str(x)[:10])
                
                # [NEW] 임의 등록 재고 발주번호 마스킹
                if 'order_no' in detail_df.columns:
                    detail_df['order_no'] = detail_df['order_no'].apply(lambda x: '-' if str(x).startswith('STOCK-') else x)

                # [NEW] 스마트 데이터 에디터 - 3. 수정 모드 분기
                if edit_mode:
                    st.info("수정할 셀을 더블클릭하여 값을 변경한 후, 하단의 '변경사항 저장' 버튼을 누르세요.")
                    
                    detail_cols_for_editor = ["id", "customer", "name", "product_type", "yarn_type", "weight", "size", "color", "shipping_unit_price", "stock", "order_no", "date", "note"]
                    for c in detail_cols_for_editor:
                        if c not in detail_df.columns: detail_df[c] = ""

                    edited_df = st.data_editor(
                        detail_df,
                        column_config={
                            "id": None, "customer": st.column_config.TextColumn("구분/발주처", disabled=True),
                            "name": st.column_config.TextColumn("제품명", disabled=True),
                            "product_type": st.column_config.TextColumn("제품종류", disabled=True),
                            "yarn_type": st.column_config.TextColumn("사종", disabled=True),
                            "weight": st.column_config.TextColumn("중량", disabled=True),
                            "size": st.column_config.TextColumn("사이즈", disabled=True),
                            "color": st.column_config.TextColumn("색상", disabled=True),
                            "shipping_unit_price": st.column_config.NumberColumn("단가", format="%d"),
                            "stock": st.column_config.NumberColumn("재고수량", format="%d"),
                            "order_no": st.column_config.TextColumn("발주번호", disabled=True),
                            "date": st.column_config.TextColumn("등록/접수일", disabled=True),
                            "note": st.column_config.TextColumn("비고", disabled=True),
                        },
                        column_order=detail_cols_for_editor,
                        hide_index=True, height=min((len(detail_df) + 1) * 35 + 3, 600),
                        key=f"inv_editor_detail_{sel_p_code}"
                    )

                    original_df_subset = detail_df.reset_index(drop=True)
                    edited_df_reset = edited_df.reset_index(drop=True)
                    changed_mask = (original_df_subset.ne(edited_df_reset)).any(axis=1)

                    if changed_mask.any():
                        if st.button("변경사항 저장", key=f"save_changes_detail_{sel_p_code}", type="primary"):
                            changed_rows = edited_df_reset[changed_mask]
                            original_changed_rows = original_df_subset[changed_mask]
                            
                            change_list = []
                            for i in changed_rows.index:
                                original_row = original_changed_rows.loc[i]
                                edited_row = changed_rows.loc[i]
                                
                                change_item = {'id': original_row['id'], 'name': original_row['name']}
                                changed_fields = {}
                                if original_row['stock'] != edited_row['stock']:
                                    changed_fields['stock'] = (original_row['stock'], edited_row['stock'])
                                if original_row['shipping_unit_price'] != edited_row['shipping_unit_price']:
                                    changed_fields['shipping_unit_price'] = (original_row['shipping_unit_price'], edited_row['shipping_unit_price'])
                                
                                if changed_fields:
                                    change_item['changes'] = changed_fields
                                    # [NEW] 화면 표시용 데이터 추가
                                    change_item['row_data'] = {
                                        '제품명': edited_row['name'],
                                        '구분/발주처': edited_row['customer'],
                                        '재고수량': edited_row['stock'],
                                        '단가': edited_row['shipping_unit_price']
                                    }
                                    change_list.append(change_item)
                            
                            st.session_state[changes_key] = change_list
                            st.rerun()
                else:
                    # 기존 조회/선택 모드
                    detail_map_view = {
                        "customer": "구분/발주처", "name": "제품명", 
                        "product_type": "제품종류", "yarn_type": "사종", "weight": "중량", 
                        "size": "사이즈", "color": "색상", "shipping_unit_price": "단가", 
                        "stock": "재고수량", "order_no": "발주번호", "date": "등록/접수일", "note": "비고"
                    }
                    detail_cols_view = ["customer", "name", "product_type", "yarn_type", "weight", "size", "color", "shipping_unit_price", "stock", "order_no", "date", "note"]
                    
                    for c in detail_cols_view:
                        if c not in detail_df.columns: detail_df[c] = ""
                    
                    if allow_shipping:
                        st.info("🔽 출고할 항목을 선택(체크)하면 하단에 출고 입력 폼이 나타납니다.")
                        sel_mode = "multi-row"
                    elif is_admin:
                        st.write("🔽 삭제할 항목을 선택(체크)하세요. (관리자 기능)")
                        sel_mode = "multi-row"
                    else:
                        sel_mode = "single-row"
                    
                    detail_height = min((len(detail_df) + 1) * 35 + 3, 600)
                    
                    selection_detail = st.dataframe(
                        detail_df[detail_cols_view].rename(columns=detail_map_view),
                        width="stretch", hide_index=True, on_select="rerun",
                        selection_mode=sel_mode, height=detail_height,
                        key=f"inv_detail_list_{sel_p_code}_{allow_shipping}"
                    )
                    
                    st.markdown(f"<div style='text-align:right; font-weight:bold; padding:5px; color:#333;'>합계 수량: {detail_df['stock'].sum():,}</div>", unsafe_allow_html=True)

                    if allow_shipping and selection_detail.selection.rows:
                        selected_rows_for_shipping = detail_df.iloc[selection_detail.selection.rows]
                    
                    if is_admin and not allow_shipping and selection_detail.selection.rows:
                        del_rows = detail_df.iloc[selection_detail.selection.rows]
                        st.markdown(f"#### 🗑️ 선택 항목 삭제 ({len(del_rows)}건)")
                        
                        if st.button("선택 항목 삭제", type="primary", key=f"btn_del_inv_sub_{sel_p_code}"):
                            st.session_state[f"confirm_del_{sel_p_code}"] = True
                        
                        if st.session_state.get(f"confirm_del_{sel_p_code}"):
                            st.warning("⚠️ 정말로 삭제하시겠습니까? (복구할 수 없습니다)")
                            if st.button("✅ 예, 삭제합니다", key=f"btn_yes_del_{sel_p_code}"):
                                for idx, row in del_rows.iterrows():
                                    db.collection("orders").document(row['id']).delete()
                                st.success("삭제되었습니다.")
                                st.session_state[f"confirm_del_{sel_p_code}"] = False
                                st.rerun()
                            if st.button("❌ 취소", key=f"btn_no_del_{sel_p_code}"):
                                st.session_state[f"confirm_del_{sel_p_code}"] = False
                                st.rerun()
                    
                    if is_admin and not allow_shipping:
                        st.divider()
                        if st.button(f"🗑️ '{sel_p_code}' 제품 재고 전체 삭제", type="secondary", key=f"btn_del_all_{sel_p_code}"):
                            st.session_state[f"confirm_del_all_{sel_p_code}"] = True
                        
                        if st.session_state.get(f"confirm_del_all_{sel_p_code}"):
                            st.warning(f"⚠️ 경고: '{sel_p_code}' 제품의 모든 재고({len(detail_df)}건)가 삭제됩니다. 이 작업은 되돌릴 수 없습니다.")
                            if st.button("✅ 예, 모두 삭제합니다", key=f"btn_yes_del_all_{sel_p_code}"):
                                for idx, row in detail_df.iterrows():
                                    db.collection("orders").document(row['id']).delete()
                                st.success("모든 재고가 삭제되었습니다.")
                                st.session_state[f"confirm_del_all_{sel_p_code}"] = False
                                st.rerun()

        
        else: # 전체 상세 내역 (리스트)
            full_df = df.copy()
            if 'date' in full_df.columns:
                full_df['date'] = full_df['date'].apply(lambda x: x.strftime('%Y-%m-%d') if not pd.isnull(x) and hasattr(x, 'strftime') else str(x)[:10])
            
            # [NEW] 임의 등록 재고 발주번호 마스킹
            if 'order_no' in full_df.columns:
                full_df['order_no'] = full_df['order_no'].apply(lambda x: '-' if str(x).startswith('STOCK-') else x)

            if edit_mode:
                st.info("수정할 셀을 더블클릭하여 값을 변경한 후, 하단의 '변경사항 저장' 버튼을 누르세요.")
                
                full_cols_for_editor = ["id", "product_code", "customer", "name", "product_type", "yarn_type", "weight", "size", "color", "shipping_unit_price", "stock", "order_no", "date", "note"]
                for c in full_cols_for_editor:
                    if c not in full_df.columns: full_df[c] = ""

                edited_df = st.data_editor(
                    full_df,
                    column_config={
                        "id": None, "product_code": st.column_config.TextColumn("제품코드", disabled=True),
                        "customer": st.column_config.TextColumn("구분/발주처", disabled=True),
                        "name": st.column_config.TextColumn("제품명", disabled=True),
                        "product_type": st.column_config.TextColumn("제품종류", disabled=True),
                        "yarn_type": st.column_config.TextColumn("사종", disabled=True),
                        "weight": st.column_config.TextColumn("중량", disabled=True),
                        "size": st.column_config.TextColumn("사이즈", disabled=True),
                        "color": st.column_config.TextColumn("색상", disabled=True),
                        "shipping_unit_price": st.column_config.NumberColumn("단가", format="%d"),
                        "stock": st.column_config.NumberColumn("재고수량", format="%d"),
                        "order_no": st.column_config.TextColumn("발주번호", disabled=True),
                        "date": st.column_config.TextColumn("등록/접수일", disabled=True),
                        "note": st.column_config.TextColumn("비고", disabled=True),
                    },
                    column_order=full_cols_for_editor,
                    hide_index=True, height=min((len(full_df) + 1) * 35 + 3, 700),
                    key=f"inv_editor_full_{allow_shipping}"
                )

                original_df_subset = full_df.reset_index(drop=True)
                edited_df_reset = edited_df.reset_index(drop=True)
                changed_mask = (original_df_subset.ne(edited_df_reset)).any(axis=1)

                if changed_mask.any():
                    if st.button("변경사항 저장", key=f"save_changes_full_{allow_shipping}", type="primary"):
                        changed_rows = edited_df_reset[changed_mask]
                        original_changed_rows = original_df_subset[changed_mask]
                        
                        change_list = []
                        for i in changed_rows.index:
                            original_row = original_changed_rows.loc[i]
                            edited_row = changed_rows.loc[i]
                            
                            change_item = {'id': original_row['id'], 'name': original_row['name']}
                            changed_fields = {}
                            if original_row['stock'] != edited_row['stock']:
                                changed_fields['stock'] = (original_row['stock'], edited_row['stock'])
                            if original_row['shipping_unit_price'] != edited_row['shipping_unit_price']:
                                changed_fields['shipping_unit_price'] = (original_row['shipping_unit_price'], edited_row['shipping_unit_price'])
                            
                            if changed_fields:
                                change_item['changes'] = changed_fields
                                # [NEW] 화면 표시용 데이터 추가
                                change_item['row_data'] = {
                                    '제품명': edited_row['name'],
                                    '구분/발주처': edited_row['customer'],
                                    '재고수량': edited_row['stock'],
                                    '단가': edited_row['shipping_unit_price']
                                }
                                change_list.append(change_item)
                        
                        st.session_state[changes_key] = change_list
                        st.rerun()
            else:
                # 기존 조회/선택 모드
                full_map = {
                    "product_code": "제품코드", "customer": "구분/발주처", "name": "제품명", 
                    "product_type": "제품종류", "yarn_type": "사종", "weight": "중량", 
                    "size": "사이즈", "color": "색상", "shipping_unit_price": "단가", 
                    "stock": "재고수량", "order_no": "발주번호", "date": "등록/접수일", "note": "비고"
                }
                full_cols = ["product_code", "customer", "name", "product_type", "yarn_type", "weight", "size", "color", "shipping_unit_price", "stock", "order_no", "date", "note"]
                
                for c in full_cols:
                    if c not in full_df.columns: full_df[c] = ""

                if allow_shipping:
                    st.info("🔽 출고할 항목을 선택(체크)하면 하단에 출고 입력 폼이 나타납니다.")
                    sel_mode = "multi-row"
                elif is_admin:
                    st.write("🔽 삭제할 항목을 선택(체크)하세요. (관리자 기능)")
                    sel_mode = "multi-row"
                else:
                    sel_mode = "single-row"

                full_height = min((len(full_df) + 1) * 35 + 3, 700)

                # [수정] 파트너인 경우 선택 기능 비활성화 (단순 조회)
                if is_partner:
                    st.dataframe(
                        full_df[full_cols].rename(columns=full_map),
                        width="stretch", hide_index=True, height=full_height,
                        key=f"inv_full_list_{allow_shipping}"
                    )
                    selection_full = None
                else:
                    selection_full = st.dataframe(
                        full_df[full_cols].rename(columns=full_map),
                        width="stretch", hide_index=True, on_select="rerun",
                        selection_mode=sel_mode, height=full_height,
                        key=f"inv_full_list_{allow_shipping}"
                    )
                
                st.markdown(f"<div style='text-align:right; font-weight:bold; padding:5px; color:#333;'>합계 수량: {full_df['stock'].sum():,}</div>", unsafe_allow_html=True)

                if allow_shipping and selection_full and selection_full.selection.rows:
                    selected_rows_for_shipping = full_df.iloc[selection_full.selection.rows]

                if is_admin and not allow_shipping and selection_full and selection_full.selection.rows:
                    del_rows = full_df.iloc[selection_full.selection.rows]
                    st.markdown(f"#### 🗑️ 재고 삭제 (선택: {len(del_rows)}건)")
                    
                    if st.button("선택 항목 삭제", type="primary", key="btn_del_inv_full"):
                        st.session_state["confirm_del_full"] = True
                    
                    if st.session_state.get("confirm_del_full"):
                        st.warning("⚠️ 정말로 삭제하시겠습니까? (복구할 수 없습니다)")
                        c_conf1, c_conf2 = st.columns(2)
                        if c_conf1.button("✅ 예, 삭제합니다", key="btn_yes_del_full"):
                            for idx, row in del_rows.iterrows():
                                db.collection("orders").document(row['id']).delete()
                            st.success("삭제되었습니다.")
                            st.session_state["confirm_del_full"] = False
                            st.rerun()
                        if c_conf2.button("❌ 취소", key="btn_no_del_full"):
                            st.session_state["confirm_del_full"] = False
                            st.rerun()

        # [MOVED] 인쇄 및 엑셀 내보내기 설정 (테이블 하단으로 이동)
        st.divider()
        
        # 1. 인쇄 옵션 설정 (Expander)
        with st.expander("인쇄 옵션 설정"):
            pe_c1, pe_c2, pe_c3 = st.columns(3)
            # [수정] 옵션명에 공백 추가하여 일관성 유지
            print_mode = pe_c1.radio("출력 모드", ["요약 목록", "제품별 상세내역(그룹)", "전체 상세내역 (리스트)"], key=f"inv_p_mode_{allow_shipping}")
            p_title = pe_c2.text_input("문서 제목", value="재고 현황", key=f"inv_p_title_{allow_shipping}")
            
            pe_c4, pe_c5, pe_c6 = st.columns(3)
            p_title_size = pe_c4.number_input("제목 크기(px)", value=24, step=1, key=f"inv_p_ts_{allow_shipping}")
            p_font_size = pe_c5.number_input("본문 글자 크기(px)", value=12, step=1, key=f"inv_p_fs_{allow_shipping}")
            p_padding = pe_c6.number_input("셀 여백(px)", value=5, step=1, key=f"inv_p_pad_{allow_shipping}")
            
            pe_c7, pe_c8 = st.columns(2)
            p_show_date = pe_c7.checkbox("출력일시 표시", value=True, key=f"inv_p_date_{allow_shipping}")
            p_show_total = pe_c8.checkbox("하단 합계수량 표시", value=True, key=f"inv_p_total_{allow_shipping}")
            
            st.caption("페이지 여백 (mm)")
            pe_m1, pe_m2, pe_m3, pe_m4 = st.columns(4)
            p_m_top = pe_m1.number_input("상단", value=15, step=1, key=f"inv_p_mt_{allow_shipping}")
            p_m_bottom = pe_m2.number_input("하단", value=15, step=1, key=f"inv_p_mb_{allow_shipping}")
            p_m_left = pe_m3.number_input("좌측", value=15, step=1, key=f"inv_p_ml_{allow_shipping}")
            p_m_right = pe_m4.number_input("우측", value=15, step=1, key=f"inv_p_mr_{allow_shipping}")
            
            pe_m5, pe_m6 = st.columns(2)
            p_bo = pe_m5.number_input("외곽선 굵기", value=1.0, step=0.1, format="%.1f", key=f"inv_p_bo_{allow_shipping}")
            p_bi = pe_m6.number_input("안쪽선 굵기", value=0.5, step=0.1, format="%.1f", key=f"inv_p_bi_{allow_shipping}")

        # 엑셀 다운로드 및 인쇄 버튼 (Expander 밖으로 이동)
        c_btn_xls, c_btn_gap, c_btn_prt = st.columns([1.5, 5, 1.5])
        
        with c_btn_xls:
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                if print_mode == "요약 목록":
                    summary[disp_cols].rename(columns=summary_cols).to_excel(writer, index=False, sheet_name="재고요약")
                else:
                    # 상세 내역은 리스트 형태로 저장
                    df_detail_final.to_excel(writer, index=False, sheet_name="상세재고")
            
            st.download_button(
                label="💾 엑셀 다운로드",
                data=buffer.getvalue(),
                file_name=f"재고현황_{datetime.date.today()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

        # 인쇄 버튼
        with c_btn_prt:
            if st.button("🖨️ 인쇄하기", key=f"inv_print_btn_{allow_shipping}", use_container_width=True):
                options = {
                    'ts': p_title_size, 'bs': p_font_size, 'pad': p_padding,
                    'dd': "block" if p_show_date else "none",
                    'mt': p_m_top, 'mb': p_m_bottom, 'ml': p_m_left, 'mr': p_m_right,
                    'bo': p_bo, 'bi': p_bi
                }
                
                # 합계 텍스트 생성
                def get_summary_text(count_text, total_qty):
                    if p_show_total:
                        return f"{count_text} / 총 재고수량: {total_qty:,}"
                    return count_text

                if print_mode == "요약 목록":
                    df_print = summary[disp_cols].rename(columns=summary_cols)
                    total_q = summary['stock'].sum()
                    html = generate_report_html(p_title, df_print, get_summary_text(f"총 {len(df_print)}개 품목", total_q), options)
                    st.components.v1.html(html, height=0, width=0)
                    
                elif print_mode == "전체 상세내역 (리스트)":
                    # 제품코드, 제품명 순으로 정렬
                    if "제품코드" in df_detail_final.columns:
                        df_detail_final = df_detail_final.sort_values(by=["제품코드", "제품명"])
                    # [FIX] 컬럼명 변경 반영 (stock -> 재고수량)
                    total_q = df_detail_final['재고수량'].sum()
                    html = generate_report_html(p_title, df_detail_final, get_summary_text(f"총 {len(df_detail_final)}건", total_q), options)
                    st.components.v1.html(html, height=0, width=0)
                    
                elif print_mode == "제품별 상세내역(그룹)":
                    # 커스텀 HTML 생성 (제품별 그룹핑)
                    print_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                    date_display = "block" if p_show_date else "none"
                    
                    html_content = f"""
                    <html>
                    <head>
                        <title>{p_title}</title>
                        <style>
                            @page {{ margin: {p_m_top}mm {p_m_right}mm {p_m_bottom}mm {p_m_left}mm; }}
                            body {{ font-family: 'Malgun Gothic', sans-serif; padding: 0; margin: 0; }}
                            h2 {{ text-align: center; margin-bottom: 5px; font-size: {p_title_size}px; }}
                            .info {{ text-align: right; font-size: 12px; margin-bottom: 10px; color: #555; display: {date_display}; }}
                            table {{ width: 100%; border-collapse: collapse; font-size: {p_font_size}px; margin-bottom: 20px; border: {p_bo}px solid #444; }}
                            th, td {{ border: {p_bi}px solid #444; padding: {p_padding}px; text-align: center; }}
                            th {{ background-color: #f0f0f0; }}
                            .group-header {{ background-color: #e6f3ff; font-weight: bold; text-align: left; padding: 8px; border: 1px solid #444; margin-top: 10px; }}
                            .no-data {{ text-align: center; padding: 10px; color: #888; }}
                            .grand-total {{ text-align: right; font-weight: bold; font-size: {p_font_size + 2}px; margin-top: 20px; border-top: 2px solid #333; padding-top: 10px; }}
                            @media screen {{ body {{ display: none; }} }}
                        </style>
                    </head>
                    <body onload="window.print()">
                        <h2>{p_title}</h2>
                        <div class="info">출력일시: {print_now}</div>
                    """
                    
                    grand_total_stock = 0
                    # 요약 목록 순서대로 반복
                    for _, row in summary.iterrows():
                        p_code = row['product_code']
                        p_name = row.get('name', '')
                        p_type = row.get('product_type', '')
                        p_stock = int(row.get('stock', 0))
                        
                        # 해당 제품의 상세 내역 필터링
                        sub_df = df_detail_final[df_detail_final['제품코드'] == p_code]
                        grand_total_stock += p_stock
                        
                        # 그룹 헤더
                        html_content += f"""
                        <div class="group-header">
                            📦 [{p_code}] {p_type} / {p_name} (총 재고: {p_stock:,})
                        </div>
                        """
                        
                        if not sub_df.empty:
                            # 상세 테이블
                            html_content += sub_df.to_html(index=False, border=1)
                        else:
                            html_content += "<div class='no-data'>상세 내역 없음</div>"
                            
                    if p_show_total:
                        html_content += f"<div class='grand-total'>총 재고수량 합계: {grand_total_stock:,}</div>"

                    html_content += "</body></html>"
                    st.components.v1.html(html_content, height=0, width=0)

        # [MOVED] 출고 처리 로직 (공통)
        if allow_shipping and selected_rows_for_shipping is not None and not selected_rows_for_shipping.empty:
            sel_rows = selected_rows_for_shipping
            
            st.divider()
            st.markdown(f"#### 선택 항목 즉시 출고 ({len(sel_rows)}건)")
            
            # [수정] 상세 배송 정보 입력 폼으로 확장 (주문별 출고와 동일하게)
            st.markdown("##### 배송 정보")
            c1, c2, c3 = st.columns(3)
            q_date = c1.date_input("출고일자", datetime.date.today())
            shipping_methods = get_common_codes("shipping_methods", ["택배", "화물", "용차", "직배송", "퀵서비스", "기타"])
            q_method = c2.selectbox("배송방법", shipping_methods)
            
            shipping_partners = get_partners("배송업체")
            q_carrier = c3.selectbox("배송업체", ["직접입력"] + shipping_partners)
            if q_carrier == "직접입력":
                final_carrier = c3.text_input("업체명 직접입력", placeholder="택배사/기사님 성함")
            else:
                final_carrier = q_carrier

            st.markdown("##### 납품처 정보")
            first_row = sel_rows.iloc[0]
            # 재고 데이터에는 배송지 정보가 없을 수 있으므로 빈 값 또는 기본값 처리
            c_d1, c_d2, c_d3 = st.columns(3)
            q_to = c_d1.text_input("납품처명", value=first_row.get('delivery_to', first_row.get('customer', '')))
            q_contact = c_d2.text_input("납품연락처", value=first_row.get('delivery_contact', ''))
            q_addr = c_d3.text_input("납품주소", value=first_row.get('delivery_address', ''))
            q_note = st.text_area("비고 (송장번호/차량번호 등)", placeholder="예: 경동택배 123-456-7890")

            st.markdown("##### 수량 및 단가 확인")
            partial_ship = False
            q_ship_qty = 0
            
            if len(sel_rows) == 1:
                first_row = sel_rows.iloc[0]
                current_stock = int(first_row.get('stock', 0))
                default_price = int(first_row.get('shipping_unit_price', 0))
                
                q_c1, q_c2 = st.columns(2)
                # [FIX] current_stock이 0일 때 오류 방지
                if current_stock > 0:
                    q_ship_qty = q_c1.number_input("출고 수량", min_value=1, max_value=current_stock, value=current_stock, step=10)
                else:
                    q_ship_qty = q_c1.number_input("출고 수량", value=0, disabled=True)
                
                if current_stock > 0 and q_ship_qty < current_stock:
                    partial_ship = True
                    st.info(f"ℹ️ 부분 출고: {q_ship_qty}장 출고 후 {current_stock - q_ship_qty}장은 재고에 남습니다.")
                
                q_price = q_c2.number_input("적용 단가 (원)", value=default_price, step=100)
                calc_qty = q_ship_qty
            else:
                total_ship_qty = sel_rows['stock'].sum()
                default_price = int(sel_rows['shipping_unit_price'].mean()) if not sel_rows.empty else 0
                
                q_c1, q_c2 = st.columns(2)
                q_c1.text_input("총 출고 수량", value=f"{total_ship_qty:,}장 (일괄 전량 출고)", disabled=True)
                q_ship_qty = total_ship_qty
                q_price = q_c2.number_input("적용 단가 (원)", value=default_price, step=100, help="선택된 항목들에 일괄 적용됩니다.")
                calc_qty = total_ship_qty

            q_vat_inc = st.checkbox("단가에 부가세 포함", value=False, key="inv_quick_ship_vat")
            if q_vat_inc:
                q_supply_price = int((calc_qty * q_price) / 1.1)
                q_vat = (calc_qty * q_price) - q_supply_price
                q_total_amount = calc_qty * q_price
            else:
                q_supply_price = calc_qty * q_price
                q_vat = int(q_supply_price * 0.1)
                q_total_amount = q_supply_price + q_vat
            st.info(f"💰 **예상 금액**: 공급가액 {q_supply_price:,}원 + 부가세 {q_vat:,}원 = 합계 {q_total_amount:,}원")
            
            st.markdown("##### 운임비 설정 (선택)")
            c_cost1, c_cost2 = st.columns(2)
            q_cost = c_cost1.number_input("운임비 (원)", min_value=0, step=1000)
            q_cost_mode = c_cost2.radio("운임비 적용 방식", ["건당 운임비", "묶음 운임비(N분할)"], horizontal=True)

            if st.button("출고 처리", type="primary"):
                # 운임비 계산
                total_items = len(sel_rows)
                cost_per_item = 0
                if total_items > 0 and q_cost > 0:
                    cost_per_item = int(q_cost / total_items) if q_cost_mode == "묶음 운임비(N분할)" else q_cost

                update_data = {
                    "status": "출고완료",
                    "shipping_date": datetime.datetime.combine(q_date, datetime.datetime.now().time()),
                    "shipping_method": q_method,
                    "shipping_carrier": final_carrier,
                    "shipping_cost": cost_per_item,
                    "shipping_unit_price": q_price,
                    "vat_included": q_vat_inc,
                    "delivery_to": q_to, "delivery_contact": q_contact, "delivery_address": q_addr,
                    "note": q_note
                }
                if partial_ship and len(sel_rows) == 1:
                    doc_id = sel_rows.iloc[0]['id']
                    doc_ref = db.collection("orders").document(doc_id)
                    org_data = doc_ref.get().to_dict()
                    new_ship_doc = org_data.copy()
                    new_ship_doc.update(update_data)
                    new_ship_doc['stock'] = q_ship_qty
                    new_ship_doc['parent_id'] = doc_id
                    db.collection("orders").add(new_ship_doc)
                    doc_ref.update({"stock": current_stock - q_ship_qty})
                    st.success("부분 출고 처리 완료!")
                else:
                    for _, row in sel_rows.iterrows():
                        db.collection("orders").document(row['id']).update(update_data)
                    st.success(f"{len(sel_rows)}건 출고 처리 완료!")
                st.rerun()
        elif allow_shipping:
            st.info("👆 목록에서 출고할 항목을 선택해주세요.")
        
    else:
        st.info("현재 보유 중인 완제품 재고가 없습니다. (모두 출고되었거나 생산 중입니다.)")

def render_inventory(db, sub_menu):
    st.header("재고 현황")
    st.info("현재 보유 중인 완제품 재고를 조회합니다.")
    
    if sub_menu == "재고 임의 등록":
        st.subheader("재고 임의 등록 (자체 생산/기존 재고)")
        st.info("발주서 없이 보유하고 있는 재고나 자체 생산분을 등록하여 출고 가능한 상태로 만듭니다.")
        
        # [NEW] 관리자 전용 엑셀 업로드 기능
        if st.session_state.get("role") == "admin":
            with st.expander("엑셀 파일로 일괄 등록 (관리자 전용)", expanded=False):
                st.markdown("""
                **업로드 규칙**
                1. 아래 **양식 다운로드** 버튼을 눌러 엑셀 파일을 받으세요.
                2. `제품코드`는 시스템에 등록된 코드와 정확히 일치해야 합니다.
                3. `수량`과 `단가`는 숫자만 입력하세요.
                """)
                
                # 양식 다운로드
                template_data = {
                    "제품코드": ["A20S0904080"],
                    "발주처": ["자체보유"],
                    "제품명": ["자체재고"],
                    "색상": ["기본"],
                    "중량": [150],
                    "사이즈": ["40*80"],
                    "수량": [100],
                    "단가": [5000],
                    "비고": ["기초재고"],
                    "등록일자": [datetime.date.today().strftime("%Y-%m-%d")]
                }
                df_template = pd.DataFrame(template_data)
                
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    df_template.to_excel(writer, index=False)
                    
                st.download_button(
                    label="📥 업로드용 양식 다운로드",
                    data=buffer.getvalue(),
                    file_name="재고등록양식.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
                
                uploaded_file = st.file_uploader("엑셀 파일 업로드", type=["xlsx", "xls"], key="inv_upload")
                
                if uploaded_file:
                    try:
                        df_upload = pd.read_excel(uploaded_file)
                        st.write("데이터 미리보기:")
                        st.dataframe(df_upload.head())
                        
                        if st.button("일괄 등록 시작", type="primary", key="btn_inv_upload"):
                            # 제품 목록 미리 가져오기 (매핑용)
                            products_ref = db.collection("products").stream()
                            product_map = {p.id: p.to_dict() for p in products_ref}
                            
                            success_count = 0
                            error_logs = []
                            
                            progress_bar = st.progress(0)
                            
                            for idx, row in df_upload.iterrows():
                                p_code = str(row.get("제품코드", "")).strip()
                                if p_code not in product_map:
                                    error_logs.append(f"{idx+2}행: 제품코드 '{p_code}'가 존재하지 않습니다.")
                                    continue
                                    
                                product_info = product_map[p_code]
                                
                                # 임의의 발주번호 생성 (STOCK-YYMMDD-UUID)
                                stock_no = f"STOCK-{datetime.datetime.now().strftime('%y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
                                
                                # 날짜 처리
                                try:
                                    reg_date_val = row.get("등록일자")
                                    if pd.isna(reg_date_val):
                                        reg_date = datetime.datetime.now()
                                    else:
                                        reg_date = pd.to_datetime(reg_date_val).to_pydatetime()
                                except:
                                    reg_date = datetime.datetime.now()
                                
                                reg_name = str(row.get("제품명", "")).strip()
                                final_name = reg_name if reg_name and reg_name != "nan" else product_info.get('product_type', '자체제품')
                                
                                # [NEW] 추가 컬럼 처리 (발주처, 색상, 중량, 사이즈)
                                reg_customer = str(row.get("발주처", "")).strip()
                                if not reg_customer or reg_customer == "nan": reg_customer = "자체보유"
                                
                                reg_color = str(row.get("색상", "")).strip()
                                if not reg_color or reg_color == "nan": reg_color = "기본"
                                
                                try:
                                    reg_weight = int(row.get("중량"))
                                except:
                                    try: reg_weight = int(product_info.get('weight', 0))
                                    except: reg_weight = 0
                                
                                reg_size = str(row.get("사이즈", "")).strip()
                                if not reg_size or reg_size == "nan": reg_size = product_info.get('size', '')

                                try:
                                    stock_val = int(row.get("수량", 0))
                                    price_val = int(row.get("단가", 0))
                                except:
                                    stock_val = 0
                                    price_val = 0

                                doc_data = {
                                    "product_code": p_code,
                                    "product_type": product_info.get('product_type'),
                                    "yarn_type": product_info.get('yarn_type'),
                                    "weight": product_info.get('weight'),
                                    "size": product_info.get('size'),
                                    "weight": reg_weight,
                                    "size": reg_size,
                                    "name": final_name,
                                    "color": "기본",
                                    "color": reg_color,
                                    "order_no": stock_no,
                                    "customer": "자체보유",
                                    "customer": reg_customer,
                                    "date": reg_date,
                                    "stock": stock_val,
                                    "shipping_unit_price": price_val,
                                    "status": "봉제완료", # 즉시 출고 가능 상태
                                    "note": str(row.get("비고", "")) if pd.notna(row.get("비고")) else ""
                                }
                                
                                db.collection("orders").add(doc_data)
                                success_count += 1
                                progress_bar.progress((idx + 1) / len(df_upload))
                                
                            if success_count > 0:
                                st.success(f"✅ {success_count}건의 재고가 등록되었습니다.")
                            
                            if error_logs:
                                st.error(f"⚠️ {len(error_logs)}건의 오류가 발생했습니다.")
                                for log in error_logs:
                                    st.write(log)
                            
                            if success_count > 0:
                                st.rerun()
                                
                    except Exception as e:
                        st.error(f"파일 처리 중 오류가 발생했습니다: {e}")
            
            st.divider()

        # 제품 목록 가져오기
        products_ref = db.collection("products").stream()
        products_list = [p.to_dict() for p in products_ref]
        if not products_list:
            st.warning("등록된 제품이 없습니다. 제품 관리에서 제품을 먼저 등록해주세요.")
        else:
            # [수정] 다중 조건 필터링을 위한 기초 코드 로드
            product_types = get_common_codes("product_types", [])
            yarn_types = get_common_codes("yarn_types_coded", [])
            weight_codes = get_common_codes("weight_codes", [])
            size_codes = get_common_codes("size_codes", [])

            # 필터링 UI
            st.markdown("##### 제품 검색 조건")
            f1, f2, f3, f4 = st.columns(4)
            
            # 옵션 생성 (전체 포함)
            pt_opts = ["전체"] + [p['name'] for p in product_types]
            yt_opts = ["전체"] + [y['name'] for y in yarn_types]
            wt_opts = ["전체"] + [w['name'] for w in weight_codes]
            sz_opts = ["전체"] + [s['name'] for s in size_codes]

            sel_pt = f1.selectbox("제품종류", pt_opts, key="inv_reg_pt")
            sel_yt = f2.selectbox("사종", yt_opts, key="inv_reg_yt")
            sel_wt = f3.selectbox("중량", wt_opts, key="inv_reg_wt")
            sel_sz = f4.selectbox("사이즈", sz_opts, key="inv_reg_sz")

            # 제품 목록 필터링
            filtered_products = products_list
            if sel_pt != "전체": filtered_products = [p for p in filtered_products if p.get('product_type') == sel_pt]
            if sel_yt != "전체": filtered_products = [p for p in filtered_products if p.get('yarn_type') == sel_yt]
            if sel_wt != "전체":
                # 선택된 중량 명칭에 해당하는 코드값(숫자)을 찾아서 비교
                target_w_code = next((w['code'] for w in weight_codes if w['name'] == sel_wt), None)
                if target_w_code:
                    filtered_products = [p for p in filtered_products if str(p.get('weight')) == str(target_w_code)]
            if sel_sz != "전체": filtered_products = [p for p in filtered_products if p.get('size') == sel_sz]

            if not filtered_products:
                st.warning("조건에 맞는 제품이 없습니다.")
            else:
                # 필터링된 제품 선택
                p_options = [f"{p['product_code']} : {p.get('name', p.get('product_type'))}" for p in filtered_products]
                
                # [수정] 제품 선택을 폼 밖으로 이동하여 상세 정보 기본값 로드
                sel_p_str = st.selectbox("제품 선택", p_options)
                sel_code = sel_p_str.split(" : ")[0]
                sel_product = next((p for p in filtered_products if p['product_code'] == sel_code), None)
                
                # 기본값 설정
                def_name = sel_product.get('product_type', '자체제품') if sel_product else ""
                def_weight = int(sel_product.get('weight', 0)) if sel_product else 0
                def_size = sel_product.get('size', '') if sel_product else ""
                
                partners = get_partners("발주처")
                
                # 폼 리셋을 위한 키
                if "stock_reg_key" not in st.session_state:
                    st.session_state["stock_reg_key"] = 0
                rk = st.session_state["stock_reg_key"]

                with st.form("stock_reg_form"):
                    st.write("상세 정보 입력")
                    
                    # Row 1: 등록일자, 발주처
                    c1, c2 = st.columns(2)
                    reg_date = c1.date_input("등록일자", datetime.date.today(), key=f"reg_date_{sel_code}_{rk}")
                    if partners:
                        reg_customer = c2.selectbox("발주처 (구분)", partners, help="거래처관리에서 등록한 '자체발주' 등을 선택하세요.", key=f"reg_cust_{sel_code}_{rk}")
                    else:
                        reg_customer = c2.text_input("발주처 (구분)", key=f"reg_cust_txt_{sel_code}_{rk}")
                    
                    # Row 2: 제품명, 색상, 수량
                    c3, c4, c5 = st.columns(3)
                    reg_name = c3.text_input("제품명", value=def_name, key=f"reg_name_{sel_code}_{rk}")
                    reg_color = c4.text_input("색상", value="기본", key=f"reg_color_{sel_code}_{rk}")
                    reg_qty = c5.number_input("재고 수량(장)", min_value=1, step=10, key=f"reg_qty_{sel_code}_{rk}")
                    
                    # Row 3: 중량, 사이즈 (추가 요청)
                    c6, c7 = st.columns(2)
                    reg_weight = c6.number_input("중량(g)", value=def_weight, step=10, key=f"reg_weight_{sel_code}_{rk}")
                    reg_size = c7.text_input("사이즈", value=def_size, key=f"reg_size_{sel_code}_{rk}")

                    # Row 4: 단가, 비고
                    c8, c9 = st.columns(2)
                    reg_price = c8.number_input("단가 (원)", min_value=0, step=100, help="재고 평가 단가", key=f"reg_price_{sel_code}_{rk}")
                    reg_note = c9.text_input("비고", value="자체재고", key=f"reg_note_{sel_code}_{rk}")

                    if st.form_submit_button("재고 등록"):
                        if sel_product:
                            # 임의의 발주번호 생성 (STOCK-YYMMDD-HHMMSS)
                            stock_no = f"STOCK-{datetime.datetime.now().strftime('%y%m%d-%H%M%S')}"
                            
                            doc_data = {
                                "product_code": sel_code,
                                "product_type": sel_product.get('product_type'),
                                "yarn_type": sel_product.get('yarn_type'),
                                "weight": reg_weight, # 입력값 사용
                                "size": reg_size,     # 입력값 사용
                                "name": reg_name,
                                "color": reg_color,
                                "order_no": stock_no,
                                "customer": reg_customer,
                                "date": datetime.datetime.combine(reg_date, datetime.datetime.now().time()),
                                "stock": reg_qty,
                                "shipping_unit_price": reg_price, # 단가 저장 (출고 단가 필드 재활용)
                                "status": "봉제완료", # 즉시 출고 가능 상태
                                "note": reg_note
                            }
                            db.collection("orders").add(doc_data)
                            st.success(f"재고가 등록되었습니다. (번호: {stock_no})")
                            st.session_state["stock_reg_key"] += 1
                            st.rerun()

    elif sub_menu == "재고 현황 조회":
        # 재고 현황 조회 (출고 기능 없음)
        render_inventory_logic(db, allow_shipping=False)

def render_product_master(db, sub_menu):
    # [NEW] 제품코드설정 메뉴 통합 처리
    if sub_menu in ["제품 종류", "사종", "중량", "사이즈"]:
        render_codes(db, sub_menu)
        return

    st.header("제품 마스터 관리")
    st.info("제품의 고유한 특성(제품종류, 사종, 중량, 사이즈)을 조합하여 제품 코드를 생성하고 관리합니다.")

    # 제품종류, 사종 기초 코드 가져오기
    # 기초코드설정 메뉴와 동일한 기본값 사용
    default_product_types = [{'name': '세면타올', 'code': 'A'}, {'name': '바스타올', 'code': 'B'}, {'name': '핸드타올', 'code': 'H'}, {'name': '발매트', 'code': 'M'}, {'name': '스포츠타올', 'code': 'S'}]
    default_yarn_types = [{'name': '20수', 'code': '20S'}, {'name': '30수', 'code': '30S'}]
    product_types_coded = get_common_codes("product_types", default_product_types)
    yarn_types_coded = get_common_codes("yarn_types_coded", default_yarn_types)
    weight_codes = get_common_codes("weight_codes", [])
    size_codes = get_common_codes("size_codes", [])

    if sub_menu == "제품 목록":
        st.subheader("등록된 제품 목록")
        # created_at 필드가 없는 과거 데이터(P0001 등)도 모두 조회하기 위해 정렬 조건 제거
        product_docs = list(db.collection("products").stream())
        if product_docs:
            products_data = [doc.to_dict() for doc in product_docs]
            df_products = pd.DataFrame(products_data)
            
            col_map = {
                "product_code": "제품코드", "product_type": "제품종류", "yarn_type": "사종",
                "weight": "중량(g)", "size": "사이즈", "unit_price": "기본단가", "created_at": "등록일"
            }
            
            if 'created_at' in df_products.columns:
                # datetime 객체로 변환 (에러 발생 시 NaT 처리)
                df_products['created_at'] = pd.to_datetime(df_products['created_at'], errors='coerce')
                # 문자열 포맷팅 (NaT는 빈 문자열로)
                df_products['created_at'] = df_products['created_at'].dt.strftime('%Y-%m-%d').fillna('')

            # 구버전 데이터 호환
            if "weaving_type" in df_products.columns and "product_type" not in df_products.columns:
                df_products.rename(columns={"weaving_type": "product_type"}, inplace=True)

            # 제품코드 기준 오름차순 정렬
            if 'product_code' in df_products.columns:
                df_products = df_products.sort_values(by='product_code', ascending=True)

            display_cols = ["product_code", "product_type", "yarn_type", "weight", "size", "unit_price", "created_at"]
            final_cols = [c for c in display_cols if c in df_products.columns] # 실제 존재하는 컬럼만 선택
            df_display = df_products[final_cols].rename(columns=col_map)
            
            st.write("🔽 삭제할 제품을 선택(체크)하세요. (다중 선택 가능)")
            selection = st.dataframe(
                df_display, 
                width="stretch", 
                hide_index=True,
                on_select="rerun",
                selection_mode="multi-row",
                key="product_list_selection"
            )
            
            # 삭제 기능
            if selection.selection.rows:
                st.divider()
                st.subheader("제품 삭제")
                st.warning(f"선택한 {len(selection.selection.rows)}개의 제품을 삭제하시겠습니까?")
                if st.button("선택한 제품 일괄 삭제", type="primary"):
                    selected_indices = selection.selection.rows
                    selected_rows = df_display.iloc[selected_indices]
                    
                    deleted_cnt = 0
                    for idx, row in selected_rows.iterrows():
                        p_code = row.get("제품코드")
                        if p_code:
                            db.collection("products").document(p_code).delete()
                            deleted_cnt += 1
                    
                    st.success(f"{deleted_cnt}건의 제품이 삭제되었습니다.")
                    st.rerun()
        else:
            st.info("등록된 제품이 없습니다.")

    elif sub_menu == "제품 등록":
        st.subheader("신규 제품 등록")

        # 등록 성공 알림 표시 (리런 후에도 유지)
        if "product_reg_msg" in st.session_state:
            st.success(st.session_state["product_reg_msg"])
            del st.session_state["product_reg_msg"]
            
        # [수정] 콤보박스 초기화 로직 (위젯 생성 전에 실행해야 함)
        if st.session_state.get("trigger_reset"):
            st.session_state["reg_pt"] = "선택하세요"
            st.session_state["reg_yt"] = "선택하세요"
            st.session_state["reg_wt"] = "선택하세요"
            st.session_state["reg_sz"] = "선택하세요"
            del st.session_state["trigger_reset"]

        # 기초 코드가 없어도 폼은 보여주되, 경고 메시지 표시
        missing_codes = []
        if not product_types_coded: missing_codes.append("제품 종류")
        if not yarn_types_coded: missing_codes.append("사종")
        if not weight_codes: missing_codes.append("중량")
        if not size_codes: missing_codes.append("사이즈")

        if missing_codes:
            st.warning(f"⚠️ 다음 기초 코드가 등록되지 않았습니다: {', '.join(missing_codes)}\n\n[기초정보관리 > 제품코드설정] 메뉴에서 해당 항목들을 먼저 등록해주세요.")

        # 코드 기준 오름차순 정렬
        if product_types_coded:
            product_types_coded.sort(key=lambda x: x.get('code', ''))
        if yarn_types_coded:
            yarn_types_coded.sort(key=lambda x: x.get('code', ''))
        if weight_codes:
            weight_codes.sort(key=lambda x: x.get('code', ''))
        if size_codes:
            size_codes.sort(key=lambda x: x.get('code', ''))

        # UI에 표시할 이름 목록 (기본값 '선택하세요' 추가)
        product_type_names = ["선택하세요"] + ([item['name'] for item in product_types_coded] if product_types_coded else [])
        yarn_type_names = ["선택하세요"] + ([item['name'] for item in yarn_types_coded] if yarn_types_coded else [])
        weight_names = ["선택하세요"] + ([item['name'] for item in weight_codes] if weight_codes else [])
        size_names = ["선택하세요"] + ([item['name'] for item in size_codes] if size_codes else [])
        # [수정] UI에 표시할 목록 (명칭 + 코드)
        def get_display_opts(items):
            return ["선택하세요"] + ([f"{item['name']} ({item['code']})" for item in items] if items else [])

        product_type_opts = get_display_opts(product_types_coded)
        yarn_type_opts = get_display_opts(yarn_types_coded)
        weight_opts = get_display_opts(weight_codes)
        size_opts = get_display_opts(size_codes)

        c1, c2 = st.columns(2)
        p_product_type_sel = c1.selectbox("제품종류", product_type_opts, key="reg_pt")
        p_yarn_type_sel = c2.selectbox("사종", yarn_type_opts, key="reg_yt")

        c3, c4 = st.columns(2)
        p_weight_sel = c3.selectbox("중량", weight_opts, key="reg_wt")
        p_size_sel = c4.selectbox("사이즈", size_opts, key="reg_sz")
        
        # [NEW] 단가 입력 필드 추가
        p_price = st.number_input("기본 단가 (원)", min_value=0, step=100, help="출고 시 기본값으로 사용됩니다.")

        # 실시간 코드 조합 및 중복 확인
        generated_code = ""
        is_valid = False
            
        # [수정] 선택된 값에서 명칭과 코드 분리
        def parse_selection(val):
            if val == "선택하세요": return "", ""
            try:
                name, code = val.rsplit(' (', 1)
                return name, code[:-1]
            except:
                return val, ""

        pt_name, pt_code = parse_selection(p_product_type_sel)
        yt_name, yt_code = parse_selection(p_yarn_type_sel)
        wt_name, wt_code = parse_selection(p_weight_sel)
        sz_name, sz_code = parse_selection(p_size_sel)

        if "선택하세요" not in [p_product_type_sel, p_yarn_type_sel, p_weight_sel, p_size_sel]:
            if all([pt_code, yt_code, wt_code, sz_code]):
                generated_code = f"{pt_code}{yt_code}{wt_code}{sz_code}"
                
                # 유효성 및 중복 확인
                if len(generated_code) != 10:
                    st.error(f"⚠️ 코드 길이가 10자리가 아닙니다. (현재 {len(generated_code)}자) - [제품코드설정]을 확인하세요.")
                elif db.collection("products").document(generated_code).get().exists:
                    st.error(f"🚫 이미 존재하는 제품코드입니다: **{generated_code}**")
                else:
                    st.success(f"✅ 생성 예정 제품코드: **{generated_code}**")
                    is_valid = True

        if st.button("제품 등록", type="primary", disabled=not is_valid):
            if missing_codes:
                st.error(f"기초 코드가 누락되어 제품을 등록할 수 없습니다: {', '.join(missing_codes)}")
            else:
                product_code = generated_code
                
                # 중량은 계산을 위해 숫자로 변환하여 저장
                try:
                    weight_val = int(wt_code)
                except:
                    weight_val = 0

                product_data = {
                    "product_code": product_code,
                    "product_type": pt_name,
                    "yarn_type": yt_name,
                    "weight": weight_val, # 계산용 숫자 (코드값 사용)
                    "size": sz_name,  # 표시용 이름
                    "unit_price": int(p_price), # [NEW] 단가 저장
                    "created_at": datetime.datetime.now()
                }
                db.collection("products").document(product_code).set(product_data)
                st.session_state["product_reg_msg"] = f"✅ 신규 제품코드 [{product_code}]가 성공적으로 등록되었습니다."
                # 콤보박스 초기화를 위해 리셋 플래그 설정
                st.session_state["trigger_reset"] = True
                st.rerun()

def render_partners(db, sub_menu):
    # [FIX] 메뉴 진입/변경 시 팝업 상태 초기화 (자동 팝업 방지)
    if "last_partner_submenu" not in st.session_state:
        st.session_state["last_partner_submenu"] = None
    
    if st.session_state["last_partner_submenu"] != sub_menu:
        st.session_state["show_partner_addr_dialog"] = False
        st.session_state["last_partner_submenu"] = sub_menu

    st.header("거래처 관리")
    
    # 기초 코드에서 거래처 구분 가져오기
    partner_types = get_common_codes("partner_types", ["발주처", "염색업체", "봉제업체", "배송업체", "기타"])

    if sub_menu == "거래처 등록":
        st.subheader("거래처 등록")
        # [NEW] 폼 초기화를 위한 키 관리
        if "partner_reg_key" not in st.session_state:
            st.session_state["partner_reg_key"] = 0
        rk = st.session_state["partner_reg_key"]

        if "show_partner_addr_dialog" not in st.session_state:
            st.session_state.show_partner_addr_dialog = False

        # [NEW] 주소 검색 모달 (Dialog)
        @st.dialog("주소 검색")
        def show_address_search_modal():
            # 페이지네이션 및 검색어 상태 관리
            if "p_addr_keyword" not in st.session_state:
                st.session_state.p_addr_keyword = ""
            if "p_addr_page" not in st.session_state:
                st.session_state.p_addr_page = 1

            # 검색 폼 (Enter로 검색 가능)
            with st.form("addr_search_form_partner"):
                keyword_input = st.text_input("도로명 또는 지번 주소 입력", value=st.session_state.p_addr_keyword, placeholder="예: 세종대로 209")
                if st.form_submit_button("검색"):
                    st.session_state.p_addr_keyword = keyword_input
                    st.session_state.p_addr_page = 1 # 새 검색 시 1페이지로
                    st.rerun()

            # 검색 실행 및 결과 표시
            if st.session_state.p_addr_keyword:
                results, common, error = search_address_api(st.session_state.p_addr_keyword, st.session_state.p_addr_page)
                if error:
                    st.error(error)
                elif results:
                    st.session_state['p_addr_results'] = results
                    st.session_state['p_addr_common'] = common
                else:
                    st.warning("검색 결과가 없습니다.")
            
            if 'p_addr_results' in st.session_state:
                for idx, item in enumerate(st.session_state['p_addr_results']):
                    road = item['roadAddr']
                    zip_no = item['zipNo']
                    full_addr = f"({zip_no}) {road}"
                    if st.button(f"{full_addr}", key=f"sel_{zip_no}_{road}_{idx}"):
                        st.session_state[f"p_addr_{rk}"] = full_addr
                        # 검색 관련 세션 상태 정리
                        st.session_state.show_partner_addr_dialog = False # 팝업 닫기
                        for k in ['p_addr_keyword', 'p_addr_page', 'p_addr_results', 'p_addr_common']:
                            if k in st.session_state:
                                del st.session_state[k]
                        st.rerun()

                # 페이지네이션 UI
                common_info = st.session_state.get('p_addr_common', {})
                if common_info:
                    total_count = int(common_info.get('totalCount', 0))
                    current_page = int(common_info.get('currentPage', 1))
                    count_per_page = int(common_info.get('countPerPage', 10))
                    total_pages = (total_count + count_per_page - 1) // count_per_page if total_count > 0 else 1
                    
                    if total_pages > 1:
                        st.divider()
                        p_cols = st.columns([1, 2, 1])
                        if p_cols[0].button("◀ 이전", disabled=(current_page <= 1)):
                            st.session_state.p_addr_page -= 1
                            st.rerun()
                        p_cols[1].write(f"페이지 {current_page} / {total_pages}")
                        if p_cols[2].button("다음 ▶", disabled=(current_page >= total_pages)):
                            st.session_state.p_addr_page += 1
                            st.rerun()
            
            st.divider()
            if st.button("닫기", key="close_addr_partner", use_container_width=True):
                st.session_state.show_partner_addr_dialog = False
                st.rerun()
            
        # [NEW] 저장 성공 메시지 처리
        if "partner_success_msg" in st.session_state:
            st.success(st.session_state["partner_success_msg"])
            del st.session_state["partner_success_msg"]

        # [수정] st.form 제거 (주소 검색 팝업 유지 및 레이아웃 개선을 위해)
        c1, c2 = st.columns(2)
        p_type = c1.selectbox("거래처 구분", partner_types)
        p_name = c2.text_input("거래처명", placeholder="상호명 입력")
        
        c1, c2, c3 = st.columns(3)
        p_rep = c1.text_input("대표자명")
        p_biz_num = c2.text_input("사업자번호")
        p_item = c3.text_input("업태/종목")
        
        c1, c2, c3, c4 = st.columns(4)
        p_manager = c1.text_input("담당자")
        p_phone = c2.text_input("전화번호")
        p_fax = c3.text_input("팩스번호")
        p_email = c4.text_input("이메일")
        
        # [수정] 주소 입력 필드 레이아웃 변경 (주소 - 상세주소 - 버튼)
        ac1, ac2, ac3 = st.columns([3.5, 2, 0.5], vertical_alignment="bottom")
        p_address = ac1.text_input("주소", key=f"p_addr_{rk}")
        p_addr_detail = ac2.text_input("상세주소", placeholder="동/호수 등 입력", key=f"p_addr_det_{rk}")
        if ac3.button("🔍 주소", key=f"btn_search_addr_partner_{rk}", use_container_width=True):
            # [NEW] 팝업 열 때 검색 상태 초기화
            for k in ['p_addr_keyword', 'p_addr_page', 'p_addr_results', 'p_addr_common']:
                if k in st.session_state: del st.session_state[k]
            st.session_state.show_partner_addr_dialog = True
            st.rerun()
        if st.session_state.show_partner_addr_dialog:
            show_address_search_modal()

        p_account = st.text_input("계좌번호")
        p_note = st.text_area("기타사항")
        p_reg_date = st.date_input("등록일", datetime.date.today())
        
        if st.button("거래처 저장", type="primary"):
            if p_name:
                # 주소 합치기
                full_address = f"{p_address} {p_addr_detail}".strip()
                
                db.collection("partners").add({
                    "type": p_type,
                    "name": p_name,
                    "rep_name": p_rep,
                    "biz_num": p_biz_num,
                    "item": p_item,
                    "manager": p_manager,
                    "phone": p_phone,
                    "fax": p_fax,
                    "email": p_email,
                    "address": full_address,
                    "account": p_account,
                    "note": p_note,
                    "reg_date": datetime.datetime.combine(p_reg_date, datetime.datetime.now().time())
                })
                st.session_state["partner_success_msg"] = f"✅ {p_name} 저장 완료!"
                st.session_state["partner_reg_key"] += 1
                st.rerun()
            else:
                st.error("거래처명을 입력해주세요.")

    elif sub_menu == "거래처 목록":
        st.subheader("거래처 목록")
        # 거래처 목록 조회
        partners = list(db.collection("partners").order_by("name").stream())
        if partners:
            data = []
            for p in partners:
                p_data = p.to_dict()
                p_data['id'] = p.id
                data.append(p_data)
            df = pd.DataFrame(data)
            
            # 1. 모든 컬럼 보여주기 (빈 값이라도 표시)
            all_cols = ["name", "type", "rep_name", "biz_num", "item", "manager", "phone", "fax", "email", "address", "account", "note", "reg_date"]
            
            # 데이터프레임에 없는 컬럼은 빈 문자열로 채움
            for col in all_cols:
                if col not in df.columns:
                    df[col] = ""
            
            # [NEW] 다중 조건 검색 기능
            with st.expander("검색", expanded=True):
                sp_c1, sp_c2, sp_c3 = st.columns([1, 1, 2])
                
                # 검색 옵션 준비
                all_p_names = ["전체"] + sorted(df['name'].unique().tolist())
                all_p_types = ["전체"] + sorted(df['type'].unique().tolist())
                
                s_name = sp_c1.selectbox("거래처명", all_p_names, key="s_partner_name")
                s_type = sp_c2.selectbox("구분", all_p_types, key="s_partner_type")
                s_text = sp_c3.text_input("통합 검색 (대표자, 담당자, 연락처, 비고 등)", key="s_partner_text")
                
                # 필터링 적용
                if s_name != "전체":
                    df = df[df['name'] == s_name]
                if s_type != "전체":
                    df = df[df['type'] == s_type]
                if s_text:
                    mask = df.apply(lambda x: s_text.lower() in str(x.get('rep_name', '')).lower() or s_text.lower() in str(x.get('manager', '')).lower() or s_text.lower() in str(x.get('phone', '')).lower() or s_text.lower() in str(x.get('note', '')).lower(), axis=1)
                    df = df[mask]

            # 컬럼명 한글로 변경
            col_map = {
                "name": "거래처명", "type": "구분", "rep_name": "대표자", 
                "biz_num": "사업자번호", "item": "업태/종목", "manager": "담당자", "phone": "전화번호", 
                "fax": "팩스", "email": "이메일", "address": "주소", 
                "account": "계좌번호", "note": "비고", "reg_date": "등록일"
            }
            
            # 날짜 포맷팅
            if 'reg_date' in df.columns:
                df['reg_date'] = df['reg_date'].apply(lambda x: x.strftime('%Y-%m-%d') if not pd.isnull(x) and hasattr(x, 'strftime') else str(x)[:10])
            
            # 화면 표시용 (id 제외)
            df_display = df[all_cols].rename(columns=col_map)
            
            st.write("🔽 수정할 거래처를 선택하세요.")
            selection = st.dataframe(
                df_display, 
                hide_index=True,
                on_select="rerun", 
                selection_mode="single-row", 
                key="partner_list"
            )
            
            # 엑셀 다운로드
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_display.to_excel(writer, index=False)
            
            st.download_button(
                label="💾 엑셀 다운로드",
                data=buffer.getvalue(),
                file_name="거래처목록.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            
            # 선택 시 수정 폼 표시
            if selection.selection.rows:
                idx = selection.selection.rows[0]
                sel_row = df.iloc[idx] # 화면용 df_display가 아닌 원본 df에서 가져옴 (id 포함)
                sel_id = sel_row['id']
                
                st.divider()
                st.subheader(f"거래처 수정: {sel_row['name']}")
                
                with st.form("edit_partner_form"):
                    c1, c2 = st.columns(2)
                    e_name = c1.text_input("거래처명", value=sel_row['name'])
                    e_type = c2.selectbox("거래처 구분", partner_types, index=partner_types.index(sel_row['type']) if sel_row['type'] in partner_types else 0)
                    
                    c1, c2, c3 = st.columns(3)
                    e_rep = c1.text_input("대표자명", value=sel_row['rep_name'])
                    e_biz = c2.text_input("사업자번호", value=sel_row['biz_num'])
                    e_item = c3.text_input("업태/종목", value=sel_row['item'])
                    
                    c1, c2, c3, c4 = st.columns(4)
                    e_manager = c1.text_input("담당자", value=sel_row.get('manager', ''))
                    e_phone = c2.text_input("전화번호", value=sel_row['phone'])
                    e_fax = c3.text_input("팩스번호", value=sel_row['fax'])
                    e_email = c4.text_input("이메일", value=sel_row['email'])
                    
                    e_addr = st.text_input("주소", value=sel_row['address'])
                    e_acc = st.text_input("계좌번호", value=sel_row['account'])
                    e_note = st.text_area("기타사항", value=sel_row['note'])
                    
                    try:
                        default_date = pd.to_datetime(sel_row.get('reg_date')).date()
                    except:
                        default_date = datetime.date.today()
                    e_reg_date = st.date_input("등록일", value=default_date)
                    
                    if st.form_submit_button("수정 저장"):
                        db.collection("partners").document(sel_id).update({
                            "type": e_type,
                            "name": e_name,
                            "rep_name": e_rep,
                            "biz_num": e_biz,
                            "item": e_item,
                            "manager": e_manager,
                            "phone": e_phone,
                            "fax": e_fax,
                            "email": e_email,
                            "address": e_addr,
                            "account": e_acc,
                            "note": e_note,
                            "reg_date": datetime.datetime.combine(e_reg_date, datetime.datetime.now().time())
                        })
                        st.success("수정되었습니다.")
                        st.rerun()
            
            # 2. 거래처 삭제 기능
            st.divider()
            st.subheader("거래처 삭제")
            
            # 이름으로 ID 매핑 (삭제용)
            id_map = {row['name']: row['id'] for row in data}
            delete_list = st.multiselect("삭제할 거래처를 선택하세요", list(id_map.keys()))
            
            if st.button("선택한 거래처 삭제"):
                if delete_list:
                    for name in delete_list:
                        db.collection("partners").document(id_map[name]).delete()
                    st.success("삭제되었습니다.")
                    st.rerun()
        else:
            st.info("등록된 거래처가 없습니다.")

    elif sub_menu == "거래처 구분 관리":
        st.subheader("거래처 구분 관리")
        st.info("거래처 등록 시 사용할 구분을 관리합니다.")
        manage_code("partner_types", partner_types, "거래처 구분")

    elif sub_menu == "배송방법 관리":
        st.subheader("배송방법 관리")
        st.info("출고 작업 시 선택할 배송방법을 관리합니다.")
        manage_code("shipping_methods", ["택배", "화물", "용차", "직배송", "퀵서비스", "기타"], "배송방법")

def render_machines(db, sub_menu):
    st.header("제직기 관리")
    
    if sub_menu == "제직기 등록":
        st.subheader("제직기 등록")
        st.info("신규 제직기를 등록합니다. 이미 등록된 호기 번호는 사용할 수 없습니다.")
        
        # [NEW] 저장 성공 메시지
        if st.session_state.get("machine_reg_success"):
            st.success("✅ 제직기 정보가 저장되었습니다.")
            st.session_state["machine_reg_success"] = False

        with st.form("add_machine_form_new", clear_on_submit=True):
            c1, c2 = st.columns(2)
            new_no = c1.number_input("호기 번호 (No.)", min_value=1, step=1, help="정렬 순서 및 고유 ID로 사용됩니다.")
            new_name = c2.text_input("제직기 명칭", placeholder="예: 1호대")
            c3, c4, c5 = st.columns(3)
            new_model = c3.text_input("모델명")
            new_loom = c4.text_input("직기타입")
            new_jacquard = c5.text_input("자가드타입")
            new_note = st.text_input("특이사항/메모")
            
            if st.form_submit_button("저장"):
                doc_ref = db.collection("machines").document(str(new_no))
                if doc_ref.get().exists:
                    st.error(f"⛔ 이미 등록된 호기 번호입니다: {new_no}호기")
                else:
                    doc_ref.set({
                        "machine_no": new_no,
                        "name": new_name,
                        "model": new_model,
                        "loom_type": new_loom,
                        "jacquard_type": new_jacquard,
                        "note": new_note
                    })
                    st.session_state["machine_reg_success"] = True
                    st.rerun()

    elif sub_menu == "제직기 목록":
        st.subheader("제직기 목록")
        machines_ref = db.collection("machines").order_by("machine_no")
        m_docs = list(machines_ref.stream())
        m_list = []
        for d in m_docs:
            item = d.to_dict()
            item['id'] = d.id
            m_list.append(item)
        
        if not m_list:
            st.warning("등록된 제직기가 없습니다.")
            if st.button("기본 제직기(1~9호대) 자동 생성"):
                for i in range(1, 10):
                    db.collection("machines").document(str(i)).set({
                        "machine_no": i,
                        "name": f"{i}호대",
                        "model": "",
                        "note": ""
                    })
                st.success("기본 제직기가 생성되었습니다.")
                st.rerun()
        else:
            df = pd.DataFrame(m_list)
            col_map = {"machine_no": "호기", "name": "명칭", "model": "모델명", "note": "비고"}
            # 신규 컬럼이 없는 경우를 대비해 빈 값으로 초기화
            for col in ["loom_type", "jacquard_type"]:
                if col not in df.columns:
                    df[col] = ""
            col_map = {"machine_no": "호기", "name": "명칭", "model": "모델명", "loom_type": "직기타입", "jacquard_type": "자가드타입", "note": "비고"}
            
            # 화면 표시용
            df_display = df[["machine_no", "name", "model", "loom_type", "jacquard_type", "note"]].rename(columns=col_map)
            
            st.write("🔽 수정할 제직기를 선택하세요.")
            selection = st.dataframe(df_display, width="stretch", hide_index=True, on_select="rerun", selection_mode="single-row", key="machine_list")
            
            # 엑셀 다운로드
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_display.to_excel(writer, index=False)
            st.download_button(label="💾 엑셀 다운로드", data=buffer.getvalue(), file_name="제직기목록.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            
            if selection.selection.rows:
                idx = selection.selection.rows[0]
                # DataFrame 대신 원본 리스트 사용 (KeyError 방지)
                sel_item = m_list[idx]
                sel_id = sel_item['id']
                
                st.divider()
                st.subheader(f"제직기 수정: {sel_item['name']}")
                
                with st.form("edit_machine_form"):
                    c1, c2 = st.columns(2)
                    e_no = c1.number_input("호기 번호", value=int(sel_item['machine_no']), step=1, disabled=True)
                    e_name = c2.text_input("명칭", value=sel_item['name'])
                    c3, c4, c5 = st.columns(3)
                    e_model = c3.text_input("모델명", value=sel_item.get('model', ''))
                    e_loom = c4.text_input("직기타입", value=sel_item.get('loom_type', ''))
                    e_jacquard = c5.text_input("자가드타입", value=sel_item.get('jacquard_type', ''))
                    e_note = st.text_input("비고", value=sel_item.get('note', ''))
                    
                    if st.form_submit_button("수정 저장"):
                        db.collection("machines").document(sel_id).update({
                            "name": e_name, 
                            "model": e_model, 
                            "loom_type": e_loom,
                            "jacquard_type": e_jacquard,
                            "note": e_note
                        })
                        st.success("수정되었습니다.")
                        st.rerun()
                
                if st.button("🗑️ 이 제직기 삭제", type="primary"):
                    db.collection("machines").document(sel_id).delete()
                    st.success("삭제되었습니다.")
                    st.rerun()

def render_codes(db, sub_menu):
    st.header("제품코드 설정")
    st.info("제품 코드 생성을 위한 각 부분의 코드 및 포맷을 설정합니다.")

    if sub_menu == "제품 종류":
        manage_code_with_code("product_types", [{'name': '세면타올', 'code': 'A'}, {'name': '바스타올', 'code': 'B'}, {'name': '핸드타올', 'code': 'H'}, {'name': '발매트', 'code': 'M'}, {'name': '스포츠타올', 'code': 'S'}], "제품 종류")
    
    elif sub_menu == "사종":
        manage_code_with_code("yarn_types_coded", [{'name': '20수', 'code': '20S'}, {'name': '30수', 'code': '30S'}], "사종")

    elif sub_menu == "중량":
        manage_code_with_code("weight_codes", [], "중량")

    elif sub_menu == "사이즈":
        manage_code_with_code("size_codes", [], "사이즈")

def render_users(db, sub_menu):
    st.header("사용자 관리")
    if st.session_state.get("role") != "admin":
        st.error("관리자 권한이 필요합니다.")
    else:
        st.info("시스템 사용자를 등록하고 권한을 설정합니다.")
        
        all_menus = ["발주서접수", "발주현황", "제직현황", "제직조회", "염색현황", "봉제현황", "출고현황", "재고현황", "제품 관리", "거래처관리", "제직기관리", "제품코드설정", "사용자 관리", "발주현황(거래처)", "재고현황(거래처)"]
        
        if sub_menu == "사용자 목록":
            # 사용자 목록 조회
            users_ref = db.collection("users").stream()
            users_list = []
            for doc in users_ref:
                u = doc.to_dict()
                u['id'] = doc.id # 문서 ID를 식별자로 사용
                users_list.append(u)
            
            if users_list:
                df_users = pd.DataFrame(users_list)
                # 표시할 컬럼 정리
                display_cols = ["username", "name", "role", "department", "phone", "permissions"]
                for c in display_cols:
                    if c not in df_users.columns: df_users[c] = ""
                
                st.write("🔽 수정할 사용자를 선택하세요.")
                selection = st.dataframe(
                    df_users[display_cols],
                    width="stretch",
                    hide_index=True,
                    on_select="rerun",
                    selection_mode="single-row",
                    key="user_list"
                )
                
                if selection.selection.rows:
                    idx = selection.selection.rows[0]
                    sel_user = df_users.iloc[idx]
                    sel_uid = sel_user['username']
                    
                    st.divider()
                    st.subheader(f"사용자 수정: {sel_user['name']} ({sel_uid})")
                    
                    c1, c2 = st.columns(2)
                    e_name = c1.text_input("이름", value=sel_user['name'], key=f"e_name_{sel_uid}")
                    
                    role_opts = ["admin", "user", "partner"]
                    curr_role = sel_user['role'] if sel_user['role'] in role_opts else "user"
                    e_role = c2.selectbox("권한(Role)", role_opts, index=role_opts.index(curr_role), key=f"e_role_{sel_uid}")
                    
                    c3, c4 = st.columns(2)
                    e_dept = c3.text_input("부서/직책", value=sel_user.get('department', ''), key=f"e_dept_{sel_uid}")
                    e_phone = c4.text_input("연락처", value=sel_user.get('phone', ''), key=f"e_phone_{sel_uid}")
                    
                    # 권한 설정
                    current_perms = sel_user['permissions'] if isinstance(sel_user['permissions'], list) else []
                    
                    # [수정] 파트너인 경우 메뉴 제한
                    if e_role == "partner":
                        menu_opts = ["발주현황(거래처)", "재고현황(거래처)"]
                        # 기존 권한이 파트너 메뉴와 맞지 않으면 기본값 설정
                        if not any(p in menu_opts for p in current_perms):
                             default_edit_perms = ["발주현황(거래처)", "재고현황(거래처)"]
                        else:
                             default_edit_perms = [p for p in current_perms if p in menu_opts]
                    else:
                        menu_opts = all_menus
                        default_edit_perms = [p for p in current_perms if p in menu_opts]
                    
                    # [FIX] key에 role을 포함시켜 역할 변경 시 위젯 초기화 유도
                    e_perms = st.multiselect("접근 가능 메뉴", menu_opts, default=default_edit_perms, key=f"e_perms_{sel_uid}_{e_role}")
                    
                    # [NEW] 거래처 계정일 경우 연동 거래처 선택
                    e_linked_partner = ""
                    if e_role == "partner":
                        partners = get_partners("발주처")
                        curr_lp = sel_user.get('linked_partner', '')
                        idx_lp = partners.index(curr_lp) if curr_lp in partners else 0
                        e_linked_partner = st.selectbox("연동 거래처 (발주처)", partners, index=idx_lp, key=f"e_lp_{sel_uid}")
                    
                    new_pw = st.text_input("비밀번호 변경 (비워두면 유지)", type="password", key=f"e_pw_{sel_uid}")
                    
                    if st.button("수정 저장", key=f"btn_save_{sel_uid}"):
                        updates = {
                            "name": e_name, "role": e_role, "department": e_dept, "phone": e_phone, "permissions": e_perms,
                            "linked_partner": e_linked_partner
                        }
                        if new_pw:
                            updates["password"] = new_pw
                        
                        db.collection("users").document(sel_uid).update(updates)
                        st.success("사용자 정보가 수정되었습니다.")
                        st.rerun()
                    
                    # [NEW] 비밀번호 초기화 버튼
                    if st.button("🔑 비밀번호 초기화 (0000)", key=f"btn_reset_pw_{sel_uid}", help="비밀번호를 '0000'으로 초기화합니다. 사용자는 다음 로그인 시 새 비밀번호를 설정해야 합니다."):
                        db.collection("users").document(sel_uid).update({"password": "0000"})
                        st.success(f"{sel_user['name']}님의 비밀번호가 '0000'으로 초기화되었습니다.")
                        st.rerun()
                    
                    if st.button("🗑️ 사용자 삭제", type="primary", key=f"btn_del_{sel_uid}"):
                        db.collection("users").document(sel_uid).delete()
                        st.success("사용자가 삭제되었습니다.")
                        st.rerun()
        
        elif sub_menu == "사용자 등록":
            st.subheader("신규 사용자 등록")
            
            # [NEW] 등록 성공 메시지 표시 (리런 후 확인)
            if "user_reg_success" in st.session_state:
                st.success(st.session_state["user_reg_success"])
                del st.session_state["user_reg_success"]

            # [NEW] 입력 폼 초기화를 위한 키 생성
            if "user_reg_key" not in st.session_state:
                st.session_state["user_reg_key"] = 0
            rk = st.session_state["user_reg_key"]

            # [수정] st.form 제거하여 동적 UI(권한 변경 시 거래처 선택) 즉시 반응하도록 변경
            c1, c2 = st.columns(2)
            u_id = c1.text_input("아이디 (ID)", key=f"new_u_id_{rk}")
            u_pw = c2.text_input("비밀번호", type="password", key=f"new_u_pw_{rk}")
            c3, c4 = st.columns(2)
            u_name = c3.text_input("이름", key=f"new_u_name_{rk}")
            u_role = c4.selectbox("권한", ["user", "admin", "partner"], key=f"new_u_role_{rk}")
            c5, c6 = st.columns(2)
            u_dept = c5.text_input("부서/직책", key=f"new_u_dept_{rk}")
            u_phone = c6.text_input("연락처", key=f"new_u_phone_{rk}")
            
            u_linked_partner = ""
            if u_role == "partner":
                partners = get_partners("발주처")
                if partners:
                    u_linked_partner = st.selectbox("연동 거래처 (발주처)", partners, key=f"new_u_lp_{rk}")
                else:
                    st.warning("등록된 발주처가 없습니다.")
            
            # [수정] 파트너인 경우 메뉴 제한 및 기본값 설정
            if u_role == "partner":
                menu_opts = ["발주현황(거래처)", "재고현황(거래처)"]
                default_perms = ["발주현황(거래처)", "재고현황(거래처)"]
            else:
                menu_opts = all_menus
                default_perms = ["발주서접수", "발주현황"]
            
            # [FIX] key에 role을 포함시켜 역할 변경 시 위젯 초기화 유도
            u_perms = st.multiselect("접근 가능 메뉴", menu_opts, default=default_perms, key=f"new_u_perms_{rk}_{u_role}")
            
            if st.button("사용자 등록", type="primary", key=f"btn_add_new_user_{rk}"):
                if u_id and u_pw and u_name:
                    if db.collection("users").document(u_id).get().exists:
                        st.error("이미 존재하는 아이디입니다.")
                    else:
                        db.collection("users").document(u_id).set({
                            "username": u_id, "password": u_pw, "name": u_name, "role": u_role,
                            "department": u_dept, "phone": u_phone, "permissions": u_perms,
                            "created_at": datetime.datetime.now(),
                            "linked_partner": u_linked_partner
                        })
                        
                        # [수정] 메시지를 세션에 저장하고 리런 (화면 갱신 후 메시지 표시 및 필드 초기화)
                        st.session_state["user_reg_success"] = f"✅ 사용자 {u_name}({u_id}) 등록이 완료되었습니다."
                        
                        # [수정] 키를 증가시켜 입력 필드 초기화
                        st.session_state["user_reg_key"] += 1
                        st.rerun()
                else:
                    st.warning("아이디, 비밀번호, 이름은 필수 입력입니다.")

def render_my_profile(db):
    st.header("로그인 정보 설정")
    
    user_id = st.session_state.get("user_id")
    if not user_id:
        st.error("로그인 정보가 없습니다.")
        return

    user_doc = db.collection("users").document(user_id).get()
    if not user_doc.exists:
        st.error("사용자 정보를 찾을 수 없습니다.")
        return
    
    user_data = user_doc.to_dict()
    
    st.subheader(f"내 정보 수정 ({user_data.get('name')}님)")
    
    with st.form("my_profile_form"):
        st.write("📝 기본 정보")
        c1, c2 = st.columns(2)
        new_phone = c1.text_input("연락처", value=user_data.get("phone", ""))
        new_dept = c2.text_input("부서/직책", value=user_data.get("department", ""))
        
        st.divider()
        st.write("🔒 비밀번호 변경 (변경 시에만 입력하세요)")
        cur_pw = st.text_input("현재 비밀번호", type="password")
        new_pw = st.text_input("새 비밀번호", type="password")
        new_pw_chk = st.text_input("새 비밀번호 확인", type="password")
        
        if st.form_submit_button("정보 수정 저장"):
            updates = {}
            
            if new_phone != user_data.get("phone", ""):
                updates["phone"] = new_phone
            if new_dept != user_data.get("department", ""):
                updates["department"] = new_dept
                st.session_state["department"] = new_dept
            
            if new_pw:
                if cur_pw != user_data.get("password"):
                    st.error("현재 비밀번호가 일치하지 않습니다.")
                    return
                if new_pw != new_pw_chk:
                    st.error("새 비밀번호가 서로 일치하지 않습니다.")
                    return
                updates["password"] = new_pw
            
            if updates:
                db.collection("users").document(user_id).update(updates)
                st.success("정보가 성공적으로 수정되었습니다.")
                if "password" in updates:
                    st.info("비밀번호가 변경되었습니다.")
            else:
                st.info("변경할 내용이 없습니다.")

def render_company_settings(db, sub_menu):
    # [FIX] 메뉴 진입/변경 시 팝업 상태 초기화 (자동 팝업 방지)
    if "last_comp_submenu" not in st.session_state:
        st.session_state["last_comp_submenu"] = None
        
    if st.session_state["last_comp_submenu"] != sub_menu:
        st.session_state["show_company_addr_dialog"] = False
        st.session_state["last_comp_submenu"] = sub_menu

    doc_ref = db.collection("settings").document("company_info")
    doc = doc_ref.get()
    data = doc.to_dict() if doc.exists else {}
    
    if sub_menu == "회사정보 조회":
        st.header("회사정보")
        
        # 1. 현재 정보 표시 (View Mode)
        if data:
            st.markdown(f"""
            <div style="padding: 20px; background-color: #f8f9fa; border-radius: 10px; border: 1px solid #e9ecef; margin-bottom: 20px;">
                <h3 style="margin-top: 0; color: #333;">🏢 {data.get('name', '회사명 미등록')}</h3>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; font-size: 0.95rem;">
                    <div><strong>대표자:</strong> {data.get('rep_name', '')}</div>
                    <div><strong>사업자번호:</strong> {data.get('biz_num', '')}</div>
                    <div><strong>전화번호:</strong> {data.get('phone', '')}</div>
                    <div><strong>팩스:</strong> {data.get('fax', '')}</div>
                    <div><strong>이메일:</strong> {data.get('email', '')}</div>
                    <div><strong>업태/종목:</strong> {data.get('biz_type', '')} / {data.get('biz_item', '')}</div>
                </div>
                <div style="margin-top: 10px; font-size: 0.95rem;">
                    <strong>주소:</strong> {data.get('address', '')}
                </div>
                <hr style="margin: 15px 0; border: 0; border-top: 1px solid #ddd;">
                <div style="font-size: 0.95rem;">
                    <strong>거래은행:</strong> {data.get('bank_name', '')} {data.get('bank_account', '')}<br>
                    <strong>비고:</strong> {data.get('note', '')}
                </div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.warning("등록된 회사 정보가 없습니다. '정보 수정' 메뉴에서 정보를 입력해주세요.")

    elif sub_menu == "정보 수정":
        st.header("회사정보 수정")
        st.info("거래명세서 등 출력물에 표시될 우리 회사의 정보를 등록하거나 수정합니다.")

        # 2. 정보 수정 (Edit Mode)
        with st.form("company_info_form"):
            c1, c2 = st.columns(2)
            name = c1.text_input("상호(회사명)", value=data.get("name", ""))
            rep_name = c2.text_input("대표자명", value=data.get("rep_name", ""))
            
            c3, c4 = st.columns(2)
            biz_num = c3.text_input("사업자등록번호", value=data.get("biz_num", ""))
            address = c4.text_input("사업장 주소", value=data.get("address", ""))
            
            c5, c6 = st.columns(2)
            phone = c5.text_input("전화번호", value=data.get("phone", ""))
            fax = c6.text_input("팩스번호", value=data.get("fax", ""))
            
            c7, c8 = st.columns(2)
            biz_type = c7.text_input("업태", value=data.get("biz_type", ""))
            biz_item = c8.text_input("종목", value=data.get("biz_item", ""))
            
            email = st.text_input("이메일", value=data.get("email", ""))
            
            c9, c10 = st.columns(2)
            bank_name = c9.text_input("거래은행", value=data.get("bank_name", ""))
            bank_account = c10.text_input("계좌번호", value=data.get("bank_account", ""))
            
            note = st.text_area("비고 / 하단 문구", value=data.get("note", ""), help="명세서 하단에 들어갈 안내 문구 등을 입력하세요.")
            
            if st.form_submit_button("저장", type="primary"):
                new_data = {
                    "name": name, "rep_name": rep_name, "biz_num": biz_num, "address": address,
                    "phone": phone, "fax": fax, "biz_type": biz_type, "biz_item": biz_item,
                    "email": email, "bank_name": bank_name, "bank_account": bank_account, "note": note
                }
                doc_ref.set(new_data)
                st.success("회사 정보가 저장되었습니다.")
                st.rerun()

def render_my_profile(db):
    st.header("로그인 정보 설정")
    
    user_id = st.session_state.get("user_id")
    if not user_id:
        st.error("로그인 정보가 없습니다.")
        return

    user_doc = db.collection("users").document(user_id).get()
    if not user_doc.exists:
        st.error("사용자 정보를 찾을 수 없습니다.")
        return
    
    user_data = user_doc.to_dict()
    
    st.subheader(f"내 정보 수정 ({user_data.get('name')}님)")
    
    # [NEW] 자동 로그아웃 설정
    st.markdown("##### ⚙️ 환경 설정")
    current_logout_min = user_data.get("auto_logout_minutes", 60)
    
    # [수정] 시간/분 분리 입력
    c_h, c_m, _ = st.columns([1, 1, 4])
    curr_h = current_logout_min // 60
    curr_m = current_logout_min % 60
    
    new_h = c_h.number_input("자동 로그아웃 (시간)", min_value=0, max_value=8, value=curr_h, key="alo_h")
    
    # [수정] 8시간 설정 시 분 단위 비활성화 (최대 8시간 제한)
    m_disabled = (new_h == 8)
    m_value = 0 if m_disabled else curr_m
    
    new_m = c_m.number_input("자동 로그아웃 (분)", min_value=0, max_value=59, value=m_value, disabled=m_disabled, key="alo_m")
    st.caption("※ 최대 8시간까지 설정 가능합니다.")
    
    if st.button("환경 설정 저장"):
        total_min = new_h * 60 + new_m
        if total_min == 0: total_min = 10 # 최소 10분 안전장치
        if total_min > 480: total_min = 480
        
        db.collection("users").document(user_id).update({"auto_logout_minutes": total_min})
        st.session_state["auto_logout_minutes"] = total_min # 세션 즉시 반영
        st.success(f"자동 로그아웃 시간이 {new_h}시간 {new_m}분으로 설정되었습니다.")
        st.rerun()

    with st.form("my_profile_form"):
        st.write("📝 기본 정보")
        c1, c2 = st.columns(2)
        new_phone = c1.text_input("연락처", value=user_data.get("phone", ""))
        new_dept = c2.text_input("부서/직책", value=user_data.get("department", ""))
        
        st.divider()
        st.write("🔒 비밀번호 변경 (3개월 주기 변경 권장)")
        cur_pw = st.text_input("현재 비밀번호", type="password")
        new_pw = st.text_input("새 비밀번호", type="password")
        new_pw_chk = st.text_input("새 비밀번호 확인", type="password")
        
        if st.form_submit_button("정보 수정 저장"):
            updates = {}
            
            if new_phone != user_data.get("phone", ""):
                updates["phone"] = new_phone
            if new_dept != user_data.get("department", ""):
                updates["department"] = new_dept
                st.session_state["department"] = new_dept
            
            if new_pw:
                if cur_pw != user_data.get("password"):
                    st.error("현재 비밀번호가 일치하지 않습니다.")
                    return
                if new_pw != new_pw_chk:
                    st.error("새 비밀번호가 서로 일치하지 않습니다.")
                    return
                if new_pw == cur_pw:
                    st.error("현재 비밀번호와 동일한 비밀번호는 사용할 수 없습니다.")
                    return
                
                # [NEW] 비밀번호 정책 검증
                is_valid, err_msg = validate_password(new_pw)
                if not is_valid:
                    st.error(err_msg)
                    return

                updates["password"] = new_pw
                updates["password_changed_at"] = datetime.datetime.now() # [NEW] 변경일시 저장
            
            if updates:
                db.collection("users").document(user_id).update(updates)
                st.success("정보가 성공적으로 수정되었습니다.")
                if "password" in updates:
                    st.info("비밀번호가 변경되었습니다.")
            else:
                st.info("변경할 내용이 없습니다.")

def render_company_settings(db, sub_menu):
    doc_ref = db.collection("settings").document("company_info")
    doc = doc_ref.get()
    data = doc.to_dict() if doc.exists else {}
    
    if sub_menu == "회사정보 조회":
        st.header("회사정보")
        
        # 1. 현재 정보 표시 (View Mode)
        if data:
            st.markdown(f"""
            <div style="padding: 20px; background-color: #f8f9fa; border-radius: 10px; border: 1px solid #e9ecef; margin-bottom: 20px;">
                <h3 style="margin-top: 0; color: #333;">🏢 {data.get('name', '회사명 미등록')}</h3>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; font-size: 0.95rem;">
                    <div><strong>대표자:</strong> {data.get('rep_name', '')}</div>
                    <div><strong>사업자번호:</strong> {data.get('biz_num', '')}</div>
                    <div><strong>전화번호:</strong> {data.get('phone', '')}</div>
                    <div><strong>팩스:</strong> {data.get('fax', '')}</div>
                    <div><strong>이메일:</strong> {data.get('email', '')}</div>
                    <div><strong>업태/종목:</strong> {data.get('biz_type', '')} / {data.get('biz_item', '')}</div>
                </div>
                <div style="margin-top: 10px; font-size: 0.95rem;">
                    <strong>주소:</strong> {data.get('address', '')}
                </div>
                <hr style="margin: 15px 0; border: 0; border-top: 1px solid #ddd;">
                <div style="font-size: 0.95rem;">
                    <strong>거래은행:</strong> {data.get('bank_name', '')} {data.get('bank_account', '')}<br>
                    <strong>비고:</strong> {data.get('note', '')}
                </div>
                <div style="margin-top: 10px; font-size: 0.8rem; color: #888;">
                    <strong>도로명주소 API 키:</strong> {"✅ 등록됨" if data.get('juso_api_key') else "❌ 미등록"}
                </div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.warning("등록된 회사 정보가 없습니다. '정보 수정' 메뉴에서 정보를 입력해주세요.")

    elif sub_menu == "정보 수정":
        st.header("회사정보 수정")
        st.info("거래명세서 등 출력물에 표시될 우리 회사의 정보를 등록하거나 수정합니다.")

        if "show_company_addr_dialog" not in st.session_state:
            st.session_state.show_company_addr_dialog = False

        # [NEW] 주소 검색 모달 (Dialog)
        @st.dialog("주소 검색")
        def show_address_search_modal_company():
            # 페이지네이션 및 검색어 상태 관리
            if "c_addr_keyword" not in st.session_state:
                st.session_state.c_addr_keyword = ""
            if "c_addr_page" not in st.session_state:
                st.session_state.c_addr_page = 1

            # 검색 폼 (Enter로 검색 가능)
            with st.form("addr_search_form_company"):
                keyword_input = st.text_input("도로명 또는 지번 주소 입력", value=st.session_state.c_addr_keyword, placeholder="예: 세종대로 209")
                if st.form_submit_button("검색"):
                    st.session_state.c_addr_keyword = keyword_input
                    st.session_state.c_addr_page = 1 # 새 검색 시 1페이지로
                    st.rerun()

            # 검색 실행 및 결과 표시
            if st.session_state.c_addr_keyword:
                results, common, error = search_address_api(st.session_state.c_addr_keyword, st.session_state.c_addr_page)
                if error:
                    st.error(error)
                elif results:
                    st.session_state['c_addr_results'] = results
                    st.session_state['c_addr_common'] = common
                else:
                    st.warning("검색 결과가 없습니다.")
            
            if 'c_addr_results' in st.session_state:
                for idx, item in enumerate(st.session_state['c_addr_results']):
                    road = item['roadAddr']
                    zip_no = item['zipNo']
                    full_addr = f"({zip_no}) {road}"
                    if st.button(f"{full_addr}", key=f"sel_c_{zip_no}_{road}_{idx}"):
                        st.session_state["company_addr_input"] = full_addr
                        # 검색 관련 세션 상태 정리
                        st.session_state.show_company_addr_dialog = False # 팝업 닫기
                        for k in ['c_addr_keyword', 'c_addr_page', 'c_addr_results', 'c_addr_common']:
                            if k in st.session_state:
                                del st.session_state[k]
                        st.rerun()

                # 페이지네이션 UI
                common_info = st.session_state.get('c_addr_common', {})
                if common_info:
                    total_count = int(common_info.get('totalCount', 0))
                    current_page = int(common_info.get('currentPage', 1))
                    count_per_page = int(common_info.get('countPerPage', 10))
                    total_pages = (total_count + count_per_page - 1) // count_per_page if total_count > 0 else 1
                    
                    if total_pages > 1:
                        st.divider()
                        p_cols = st.columns([1, 2, 1])
                        if p_cols[0].button("◀ 이전", disabled=(current_page <= 1)):
                            st.session_state.c_addr_page -= 1
                            st.rerun()
                        p_cols[1].write(f"페이지 {current_page} / {total_pages}")
                        if p_cols[2].button("다음 ▶", disabled=(current_page >= total_pages)):
                            st.session_state.c_addr_page += 1
                            st.rerun()
            
            st.divider()
            if st.button("닫기", key="close_addr_company", use_container_width=True):
                st.session_state.show_company_addr_dialog = False
                st.rerun()

        # 2. 정보 수정 (Edit Mode)
        # [수정] st.form 제거 (주소 검색 팝업 유지 및 레이아웃 개선을 위해)
        c1, c2 = st.columns(2)
        name = c1.text_input("상호(회사명)", value=data.get("name", ""))
        rep_name = c2.text_input("대표자명", value=data.get("rep_name", ""))
            
        biz_num = st.text_input("사업자등록번호", value=data.get("biz_num", ""))
        
        # [수정] 주소 입력 필드 레이아웃 변경 (주소 - 상세주소 - 버튼)
        ac1, ac2, ac3 = st.columns([3.5, 2, 0.5], vertical_alignment="bottom")
        # 세션 상태 초기화 (DB 값 우선)
        if "company_addr_input" not in st.session_state:
            st.session_state["company_addr_input"] = data.get("address", "")
        
        address = ac1.text_input("사업장 주소", key="company_addr_input")
        addr_detail = ac2.text_input("상세주소", value=data.get("address_detail", ""), key="company_addr_detail")
        if ac3.button("🔍 주소", key="btn_search_addr_company", use_container_width=True):
            # [NEW] 팝업 열 때 검색 상태 초기화
            for k in ['c_addr_keyword', 'c_addr_page', 'c_addr_results', 'c_addr_common']:
                if k in st.session_state: del st.session_state[k]
            st.session_state.show_company_addr_dialog = True
            st.rerun()
        if st.session_state.show_company_addr_dialog:
            show_address_search_modal_company()
        
        c5, c6 = st.columns(2)
        phone = c5.text_input("전화번호", value=data.get("phone", ""))
        fax = c6.text_input("팩스번호", value=data.get("fax", ""))
        
        c7, c8 = st.columns(2)
        biz_type = c7.text_input("업태", value=data.get("biz_type", ""))
        biz_item = c8.text_input("종목", value=data.get("biz_item", ""))
        
        email = st.text_input("이메일", value=data.get("email", ""))
        
        c9, c10 = st.columns(2)
        bank_name = c9.text_input("거래은행", value=data.get("bank_name", ""))
        bank_account = c10.text_input("계좌번호", value=data.get("bank_account", ""))
        
        # [NEW] 주소 검색 API 키 입력
        juso_api_key = st.text_input("도로명주소 API 승인키", value=data.get("juso_api_key", ""), type="password", help="행정안전부 개발자센터에서 발급받은 '주소검색 API' 승인키를 입력하세요.")
        
        app_title = st.text_input("시스템 제목 (브라우저 탭)", value=data.get("app_title", "타올 생산 현황 관리"), help="웹브라우저 탭에 표시될 제목입니다.")
        
        note = st.text_area("비고 / 하단 문구", value=data.get("note", ""), help="명세서 하단에 들어갈 안내 문구 등을 입력하세요.")
        
        if st.button("저장", type="primary"):
            new_data = {
                "name": name, "rep_name": rep_name, "biz_num": biz_num, 
                "address": address, "address_detail": addr_detail, # 상세주소 별도 저장 또는 합쳐서 저장 가능 (여기선 분리 저장 예시)
                "phone": phone, "fax": fax, "biz_type": biz_type, "biz_item": biz_item,
                "email": email, "bank_name": bank_name, "bank_account": bank_account, "note": note,
                "juso_api_key": juso_api_key,
                "app_title": app_title
            }
            doc_ref.set(new_data)
            st.success("회사 정보가 저장되었습니다.")
            st.rerun()
        # [NEW] 주소 검색 API 키 입력
        juso_api_key = st.text_input("도로명주소 API 승인키", value=data.get("juso_api_key", ""), type="password", help="행정안전부 개발자센터에서 발급받은 '주소검색 API' 승인키를 입력하세요.")
        
        app_title = st.text_input("시스템 제목 (브라우저 탭)", value=data.get("app_title", "타올 생산 현황 관리"), help="웹브라우저 탭에 표시될 제목입니다.")
        
        note = st.text_area("비고 / 하단 문구", value=data.get("note", ""), help="명세서 하단에 들어갈 안내 문구 등을 입력하세요.")
        
        if st.button("저장", type="primary"):
            new_data = {
                "name": name, "rep_name": rep_name, "biz_num": biz_num, 
                "address": address, "address_detail": addr_detail, # 상세주소 별도 저장 또는 합쳐서 저장 가능 (여기선 분리 저장 예시)
                "phone": phone, "fax": fax, "biz_type": biz_type, "biz_item": biz_item,
                "email": email, "bank_name": bank_name, "bank_account": bank_account, "note": note,
                "juso_api_key": juso_api_key,
                "app_title": app_title
            }
            doc_ref.set(new_data)
            st.success("회사 정보가 저장되었습니다.")
            st.rerun()