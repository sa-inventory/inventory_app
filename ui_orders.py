import streamlit as st
import pandas as pd
import datetime
import io
from firebase_admin import firestore
from utils import get_partners, generate_report_html, get_common_codes

def render_order_entry(db, sub_menu):
    st.header("발주서 접수")
    st.info("신규 발주서를 등록합니다. 개별 등록 또는 엑셀 일괄 업로드가 가능합니다.")
    
    # [NEW] 데이터프레임 리셋을 위한 동적 키 초기화
    if "order_df_key" not in st.session_state:
        st.session_state["order_df_key"] = 0

    if "del_orders_key" not in st.session_state:
        st.session_state["del_orders_key"] = 0

    # 발주 등록 성공 메시지 표시 (리런 후 유지)
    if "order_success_msg" in st.session_state:
        st.success(st.session_state["order_success_msg"])
        del st.session_state["order_success_msg"]
        
    # [수정] 발주 등록 후 초기화 로직
    if st.session_state.get("trigger_order_reset"):
        st.session_state["filter_pt"] = "전체"
        st.session_state["filter_yt"] = "전체"
        st.session_state["filter_wt"] = "전체"
        st.session_state["filter_sz"] = "전체"
        # 키 값을 변경하여 강제로 선택 해제 (새로운 데이터프레임으로 인식)
        st.session_state["order_df_key"] += 1
        del st.session_state["trigger_order_reset"]

    # 제품 목록 미리 가져오기 (공통 사용)
    product_docs = list(db.collection("products").order_by("product_code").stream())
    if not product_docs:
        st.warning("등록된 제품이 없습니다. [기초정보관리 > 제품 관리] 메뉴에서 먼저 제품을 등록해주세요.")
        st.stop()
    
    # 데이터프레임 변환 (개별 접수용)
    products_data = [doc.to_dict() for doc in product_docs]
    df_products = pd.DataFrame(products_data)
    
    # 구버전 데이터 호환
    if "weaving_type" in df_products.columns and "product_type" not in df_products.columns:
        df_products.rename(columns={"weaving_type": "product_type"}, inplace=True)

    if sub_menu == "개별 접수":
        # --- 1. 제품 선택 ---
        st.subheader("1. 제품 선택")

        # 표시할 컬럼 설정
        col_map = {
            "product_code": "제품코드", "product_type": "제품종류", "yarn_type": "사종",
            "weight": "중량(g)", "size": "사이즈"
        }
        display_cols = ["product_code", "product_type", "yarn_type", "weight", "size"]
        final_cols = [c for c in display_cols if c in df_products.columns]

        # 검색 필터 추가
        with st.expander("제품 검색조건", expanded=True):
            f1, f2, f3, f4 = st.columns(4)
            
            # 필터 옵션 생성 (전체 + 고유값)
            def get_options(col):
                if col in df_products.columns:
                    # None 값 처리 및 문자열 변환
                    values = [str(x) for x in df_products[col].unique() if pd.notna(x)]
                    return ["전체"] + sorted(values)
                return ["전체"]
            
            s_type = f1.selectbox("제품종류", get_options("product_type"), key="filter_pt")
            s_yarn = f2.selectbox("사종", get_options("yarn_type"), key="filter_yt")
            s_weight = f3.selectbox("중량(g)", get_options("weight"), key="filter_wt")
            s_size = f4.selectbox("사이즈(폭*길이)", get_options("size"), key="filter_sz")

        # 필터링 적용
        df_filtered = df_products.copy()
        if s_type != "전체":
            df_filtered = df_filtered[df_filtered['product_type'].astype(str) == s_type]
        if s_yarn != "전체":
            df_filtered = df_filtered[df_filtered['yarn_type'].astype(str) == s_yarn]
        if s_weight != "전체":
            df_filtered = df_filtered[df_filtered['weight'].astype(str) == s_weight]
        if s_size != "전체":
            df_filtered = df_filtered[df_filtered['size'].astype(str) == s_size]

        st.write("🔽 발주할 제품을 목록에서 선택(클릭)하세요.")
        selection = st.dataframe(
            df_filtered[final_cols].rename(columns=col_map),
            width="stretch",
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key=f"order_product_select_{st.session_state['order_df_key']}"
        )

        if not selection.selection.rows:
            st.info("👆 위 목록에서 제품을 선택하면 발주 입력 폼이 나타납니다.")
        else:
            idx = selection.selection.rows[0]
            selected_product = df_filtered.iloc[idx].to_dict()
            
            st.divider()
            st.success(f"선택된 제품: **{selected_product['product_code']}** ({selected_product.get('product_type', '')} / {selected_product.get('yarn_type', '')})")

            # --- 2. 발주 정보 입력 ---
            with st.form("order_form", clear_on_submit=True):
                st.subheader("2. 발주 상세 정보 입력")
                
                customer_list = get_partners("발주처")

                c1, c2, c3 = st.columns(3)
                order_date = c1.date_input("발주접수일", datetime.date.today(), format="YYYY-MM-DD")
                if customer_list:
                    customer = c2.selectbox("발주처 선택", customer_list)
                else:
                    customer = c2.text_input("발주처 (기초정보관리에서 거래처를 등록하세요)")
                delivery_req_date = c3.date_input("납품요청일", datetime.date.today() + datetime.timedelta(days=7), format="YYYY-MM-DD")

                c1, c2, c3 = st.columns(3)
                name = c1.text_input("제품명 (고객사 요청 제품명)", help="고객사가 부르는 제품명을 입력하세요. 예: 프리미엄 호텔타올")
                color = c2.text_input("색상")
                stock = c3.number_input("수량(장)", min_value=0, step=10)

                st.subheader("납품 및 기타 정보")
                c1, c2, c3 = st.columns(3)
                delivery_to = c1.text_input("납품처")
                delivery_contact = c2.text_input("납품 연락처")
                delivery_address = c3.text_input("납품 주소")
                
                note = st.text_area("특이사항")
                
                submitted = st.form_submit_button("발주 등록")
                if submitted:
                    if name and customer:
                        # 발주번호 생성 로직 (YYMM + 3자리 일련번호, 예: 2505001)
                        now = datetime.datetime.now()
                        prefix = now.strftime("%y%m") # 예: 2405
                        
                        # 해당 월의 가장 마지막 발주번호 조회 (orders 컬렉션에서)
                        last_docs = db.collection("orders")\
                            .where("order_no", ">=", f"{prefix}000")\
                            .where("order_no", "<=", f"{prefix}999")\
                            .order_by("order_no", direction=firestore.Query.DESCENDING)\
                            .limit(1)\
                            .stream()
                        
                        last_seq = 0
                        for doc in last_docs:
                            last_val = doc.to_dict().get("order_no")
                            if last_val and len(last_val) == 7:
                                try:
                                    last_seq = int(last_val[-3:])
                                except:
                                    pass
                        
                        new_seq = last_seq + 1
                        order_no = f"{prefix}{new_seq:03d}"

                        # Firestore에 저장할 데이터 딕셔너리 생성
                        doc_data = {
                            # 제품 마스터 정보 (Denormalized)
                            "product_code": selected_product['product_code'],
                            "product_type": selected_product.get('product_type', selected_product.get('weaving_type')), # 필드명 변경
                            "yarn_type": selected_product.get('yarn_type'),
                            "weight": selected_product['weight'],
                            "size": selected_product['size'],
                            
                            # 주문 고유 정보
                            "order_no": order_no,
                            "date": datetime.datetime.combine(order_date, datetime.time.min),
                            "customer": customer,
                            "delivery_req_date": str(delivery_req_date),
                            "name": name, # 고객사 제품명
                            "color": color,
                            "stock": stock,
                            "delivery_to": delivery_to,
                            "delivery_contact": delivery_contact,
                            "delivery_address": delivery_address,
                            "note": note,
                            "status": "발주접수" # 초기 상태
                        }
                        db.collection("orders").add(doc_data) # 'orders' 컬렉션에 저장
                        st.success(f"발주번호 [{order_no}] 접수 완료!")
                        st.session_state["order_success_msg"] = f"✅ 발주번호 [{order_no}]가 성공적으로 등록되었습니다."
                        st.session_state["trigger_order_reset"] = True
                        st.rerun()
                    else:
                        st.error("제품명과 발주처는 필수 입력 항목입니다.")

def render_partner_order_status(db):
    st.header("발주 현황 조회 (거래처용)")
    
    partner_name = st.session_state.get("linked_partner")
    if not partner_name:
        st.error("연동된 거래처 정보가 없습니다. 관리자에게 문의하세요.")
        return

    st.info(f"**{partner_name}**님의 발주 내역 및 현재 공정 상태를 조회합니다.")

    # 검색 조건
    with st.form("partner_search_form"):
        c1, c2, c3 = st.columns(3)
        today = datetime.date.today()
        date_range = c1.date_input("조회 기간 (접수일)", [today - datetime.timedelta(days=90), today])
        
        # 상태 필터
        status_options = ["전체", "발주접수", "제직대기", "제직중", "제직완료", "염색중", "염색완료", "봉제중", "봉제완료", "출고완료"]
        filter_status = c2.selectbox("진행 상태", status_options)
        
        # [NEW] 제품명 검색
        search_product = c3.text_input("제품명 검색", placeholder="제품명 입력")
        
        st.form_submit_button("🔍 조회하기")

    # 데이터 조회
    start_date = datetime.datetime.combine(date_range[0], datetime.time.min)
    end_date = datetime.datetime.combine(date_range[1], datetime.time.max) if len(date_range) > 1 else datetime.datetime.combine(date_range[0], datetime.time.max)

    # [수정] 복합 인덱스 오류 방지를 위해 customer로만 1차 조회 후 메모리 필터링
    docs = db.collection("orders").where("customer", "==", partner_name).stream()
    
    rows = []
    for doc in docs:
        d = doc.to_dict()
        
        # 1. 날짜 필터링 (메모리)
        d_date = d.get('date')
        if d_date:
            if d_date.tzinfo: d_date = d_date.replace(tzinfo=None)
            if not (start_date <= d_date <= end_date):
                continue
        else:
            continue
            
        # 2. 상태 필터링 (메모리)
        if filter_status != "전체" and d.get('status') != filter_status:
            continue
            
        # [NEW] 3. 제품명 검색 필터 (메모리)
        if search_product:
            if search_product not in d.get('name', ''):
                continue
            
        # 정렬을 위해 원본 날짜 임시 저장
        d['_sort_date'] = d.get('date')

        # 마스터 완료 상태 표시 변경
        if d.get('status') == "제직완료(Master)":
            d['status'] = "제직완료"
            
        if 'date' in d and d['date']:
            d['date'] = d['date'].strftime("%Y-%m-%d")
        if 'delivery_req_date' in d:
             d['delivery_req_date'] = str(d['delivery_req_date'])[:10]
             
        rows.append(d)
        
    # 3. 날짜 기준 내림차순 정렬
    rows.sort(key=lambda x: x.get('_sort_date', datetime.datetime.min), reverse=True)

    if rows:
        df = pd.DataFrame(rows)
        
        # [수정] 컬럼 매핑 확장 및 발주처 제외
        col_map = {
            "order_no": "발주번호", "status": "현재상태", "date": "접수일", 
            "name": "제품명", "product_type": "제품종류", "yarn_type": "사종",
            "color": "색상", "weight": "중량", "size": "사이즈", "stock": "발주수량", 
            "delivery_req_date": "납품요청일", "delivery_to": "납품처",
            "delivery_contact": "연락처", "delivery_address": "주소", "note": "비고"
        }
        # customer 제외, 상세 정보 포함
        display_cols = ["date", "order_no", "status", "name", "product_type", "yarn_type", "color", "weight", "size", "stock", "delivery_req_date", "delivery_to", "delivery_contact", "delivery_address", "note"]
        final_cols = [c for c in display_cols if c in df.columns]
        
        df_display = df[final_cols].rename(columns=col_map)
        
        st.write("🔽 상세 이력을 확인할 항목을 선택하세요.")
        selection = st.dataframe(
            df_display, 
            width="stretch", 
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            height=700,
            key="partner_order_list"
        )
        
        # [NEW] 선택 시 상세 이력 표시
        if selection.selection.rows:
            idx = selection.selection.rows[0]
            sel_row = df.iloc[idx]
            
            st.divider()
            st.subheader(f"상세 이력 정보: {sel_row['name']} ({sel_row['order_no']})")

            # 제직기 명칭 매핑을 위한 데이터 가져오기 (필요 시)
            machine_map = {}
            try:
                m_docs = db.collection("machines").stream()
                for m in m_docs:
                    md = m.to_dict()
                    machine_map[md.get('machine_no')] = md.get('name')
            except: pass

            # 포맷팅 함수들
            def fmt_dt(val):
                if pd.isna(val) or val == "" or val is None: return "-"
                if isinstance(val, pd.Timestamp): return val.strftime("%Y-%m-%d %H:%M")
                if isinstance(val, datetime.datetime): return val.strftime("%Y-%m-%d %H:%M")
                return str(val)[:16]
            
            def fmt_date(val):
                if pd.isna(val) or val == "" or val is None: return "-"
                if isinstance(val, pd.Timestamp): return val.strftime("%Y-%m-%d")
                if isinstance(val, datetime.datetime): return val.strftime("%Y-%m-%d")
                return str(val)[:10]

            def fmt_num(val, unit=""):
                try: return f"{int(val):,}{unit}"
                except: return "-"
            
            def fmt_float(val, unit=""):
                try: return f"{float(val):,.1f}{unit}"
                except: return "-"

            c_p1, c_p2, c_p3, c_p4 = st.columns(4)
            
            with c_p1:
                st.markdown("##### 제직 공정")
                if sel_row.get('weaving_start_time'):
                    m_no = sel_row.get('machine_no')
                    try: m_name = machine_map.get(int(m_no), str(m_no)) if pd.notna(m_no) else "-"
                    except: m_name = str(m_no)
                    st.caption("제직 설정 및 결과")
                    st.text(f"제직기    : {m_name}")
                    st.text(f"시작일시  : {fmt_dt(sel_row.get('weaving_start_time'))}")
                    st.text(f"제직롤수  : {fmt_num(sel_row.get('weaving_roll_count'), '롤')}")
                    st.markdown("---")
                    st.text(f"완료일시  : {fmt_dt(sel_row.get('weaving_end_time'))}")
                    st.text(f"생산매수  : {fmt_num(sel_row.get('real_stock'), '장')}")
                    st.text(f"중량(g)   : {fmt_num(sel_row.get('real_weight'), 'g')}")
                    st.text(f"생산중량  : {fmt_float(sel_row.get('prod_weight_kg'), 'kg')}")
                else: st.info("대기 중")

            with c_p2:
                st.markdown("##### 염색 공정")
                if sel_row.get('dyeing_out_date'):
                    st.caption("염색 출고 및 입고")
                    st.text(f"염색업체  : {sel_row.get('dyeing_partner')}")
                    st.text(f"출고일자  : {fmt_date(sel_row.get('dyeing_out_date'))}")
                    st.text(f"출고중량  : {fmt_float(sel_row.get('dyeing_out_weight'), 'kg')}")
                    st.text(f"색상정보  : {sel_row.get('dyeing_color_name')} ({sel_row.get('dyeing_color_code')})")
                    st.markdown("---")
                    st.text(f"입고일자  : {fmt_date(sel_row.get('dyeing_in_date'))}")
                    st.text(f"입고중량  : {fmt_float(sel_row.get('dyeing_in_weight'), 'kg')}")
                else: st.info("대기 중")

            with c_p3:
                st.markdown("##### 봉제 공정")
                if sel_row.get('sewing_start_date'):
                    st.caption("봉제 작업 및 결과")
                    st.text(f"봉제업체  : {sel_row.get('sewing_partner')}")
                    st.text(f"작업구분  : {sel_row.get('sewing_type')}")
                    st.text(f"시작일자  : {fmt_date(sel_row.get('sewing_start_date'))}")
                    st.markdown("---")
                    st.text(f"완료일자  : {fmt_date(sel_row.get('sewing_end_date'))}")
                    st.text(f"완료수량  : {fmt_num(sel_row.get('stock'), '장')}")
                    st.text(f"불량수량  : {fmt_num(sel_row.get('sewing_defect_qty'), '장')}")
                else: st.info("대기 중")

            with c_p4:
                st.markdown("##### 출고/배송")
                if sel_row.get('shipping_date'):
                    st.caption("출고 정보")
                    st.text(f"출고일시  : {fmt_dt(sel_row.get('shipping_date'))}")
                    st.text(f"출고방법  : {sel_row.get('shipping_method')}")
                    st.text(f"납품처    : {sel_row.get('delivery_to')}")
                    st.text(f"연락처    : {sel_row.get('delivery_contact')}")
                    st.text(f"주소      : {sel_row.get('delivery_address')}")
                else: st.info("미출고")

        st.divider()
        
        # [NEW] 인쇄 옵션 설정
        with st.expander("인쇄 옵션 설정"):
            po_c1, po_c2, po_c3, po_c4 = st.columns(4)
            p_title = po_c1.text_input("제목", value=f"발주 현황 ({partner_name})", key="po_title")
            p_title_size = po_c2.number_input("제목 크기(px)", value=24, step=1, key="po_ts")
            p_body_size = po_c3.number_input("본문 글자 크기(px)", value=11, step=1, key="po_bs")
            p_padding = po_c4.number_input("셀 여백(px)", value=6, step=1, key="po_pad")
            
            po_c5, po_c6, po_c7 = st.columns(3)
            p_show_date = po_c5.checkbox("출력일시 표시", value=True, key="po_sd")
            p_date_pos = po_c6.selectbox("일시 위치", ["Right", "Left", "Center"], index=0, key="po_dp")
            p_date_size = po_c7.number_input("일시 글자 크기(px)", value=12, step=1, key="po_ds")
            
            st.caption("페이지 여백 (mm)")
            po_c8, po_c9, po_c10, po_c11 = st.columns(4)
            p_m_top = po_c8.number_input("상단", value=15, step=1, key="po_mt")
            p_m_bottom = po_c9.number_input("하단", value=15, step=1, key="po_mb")
            p_m_left = po_c10.number_input("좌측", value=15, step=1, key="po_ml")
            p_m_right = po_c11.number_input("우측", value=15, step=1, key="po_mr")

        # 엑셀 및 인쇄 버튼
        c1, c2 = st.columns([1, 1])
        
        # 엑셀 다운로드
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df_display.to_excel(writer, index=False)
        c1.download_button(
            label="💾 엑셀 다운로드",
            data=buffer.getvalue(),
            file_name=f"발주현황_{partner_name}_{today}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
        # 인쇄 (옵션 적용)
        if c2.button("🖨️ 바로 인쇄하기"):
            options = {
                'mt': p_m_top, 'mr': p_m_right, 'mb': p_m_bottom, 'ml': p_m_left,
                'ts': p_title_size, 'bs': p_body_size, 'pad': p_padding,
                'da': p_date_pos.lower(), 'ds': p_date_size, 'dd': "block" if p_show_date else "none"
            }
            print_html = generate_report_html(p_title, df_display, "", options)
            st.components.v1.html(print_html, height=0, width=0)
    else:
        st.info("조회된 발주 내역이 없습니다.")

def render_order_status(db, sub_menu):
    st.header("발주 현황")

    # [FIX] KeyError 방지를 위해 세션 키가 없으면 초기화
    if "del_orders_key" not in st.session_state:
        st.session_state["del_orders_key"] = 0

    # [NEW] 발주내역삭제(엑셀업로드) - 관리자 전용
    if sub_menu == "발주내역삭제(엑셀업로드)" and st.session_state.get("role") == "admin":
            st.subheader("엑셀 파일로 일괄 등록")
            st.markdown("""
            **업로드 규칙**
            1. 아래 **양식 다운로드** 버튼을 눌러 엑셀 파일을 받으세요.
            2. `제품코드`는 시스템에 등록된 코드와 정확히 일치해야 합니다.
            3. `접수일자`와 `납품요청일`은 `YYYY-MM-DD` 형식으로 입력하세요.
            """)
            
            # 양식 다운로드
            template_data = {
                "접수일자": [datetime.date.today().strftime("%Y-%m-%d")],
                "발주처": ["예시상사"],
                "제품코드": ["A20S0904080"],
                "제품명(고객용)": ["호텔타올"],
                "색상": ["화이트"],
                "수량": [100],
                "납품요청일": [(datetime.date.today() + datetime.timedelta(days=7)).strftime("%Y-%m-%d")],
                "납품처": ["서울시 강남구..."],
                "납품연락처": ["010-0000-0000"],
                "납품주소": ["서울시..."],
                "비고": ["특이사항"]
            }
            df_template = pd.DataFrame(template_data)
            
            # 제품 목록 미리 가져오기 (매핑용)
            product_docs = list(db.collection("products").order_by("product_code").stream())
            products_data = [doc.to_dict() for doc in product_docs]
            # 구버전 데이터 호환
            for p in products_data:
                if "weaving_type" in p and "product_type" not in p: p["product_type"] = p["weaving_type"]
            
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_template.to_excel(writer, index=False)
                
            st.download_button(
                label="📥 업로드용 양식 다운로드",
                data=buffer.getvalue(),
                file_name="발주업로드양식.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            
            uploaded_file = st.file_uploader("엑셀 파일 업로드", type=["xlsx", "xls"])
            
            if uploaded_file:
                try:
                    df_upload = pd.read_excel(uploaded_file)
                    st.write("데이터 미리보기:")
                    st.dataframe(df_upload.head())
                    
                    if st.button("일괄 등록 시작", type="primary"):
                        # 제품 코드 매핑을 위한 딕셔너리 생성
                        product_map = {p['product_code']: p for p in products_data}
                        
                        # 발주번호 생성을 위한 마지막 번호 조회
                        now = datetime.datetime.now()
                        prefix = now.strftime("%y%m")
                        last_docs = db.collection("orders").where("order_no", ">=", f"{prefix}000").where("order_no", "<=", f"{prefix}999").order_by("order_no", direction=firestore.Query.DESCENDING).limit(1).stream()
                        last_seq = 0
                        for doc in last_docs:
                            last_val = doc.to_dict().get("order_no")
                            if last_val and len(last_val) == 7:
                                try: last_seq = int(last_val[-3:])
                                except: pass
                        
                        success_count = 0
                        error_logs = []
                        
                        progress_bar = st.progress(0)
                        
                        for idx, row in df_upload.iterrows():
                            p_code = str(row.get("제품코드", "")).strip()
                            if p_code not in product_map:
                                error_logs.append(f"{idx+2}행: 제품코드 '{p_code}'가 존재하지 않습니다.")
                                continue
                                
                            product_info = product_map[p_code]
                            last_seq += 1
                            order_no = f"{prefix}{last_seq:03d}"
                            
                            # 날짜 처리
                            try:
                                reg_date = pd.to_datetime(row.get("접수일자", datetime.date.today())).to_pydatetime()
                            except:
                                reg_date = datetime.datetime.now()
                                
                            doc_data = {
                                "product_code": p_code,
                                "product_type": product_info.get('product_type', product_info.get('weaving_type')),
                                "yarn_type": product_info.get('yarn_type'),
                                "weight": product_info.get('weight'),
                                "size": product_info.get('size'),
                                
                                "order_no": order_no,
                                "date": reg_date,
                                "customer": str(row.get("발주처", "")),
                                "delivery_req_date": str(row.get("납품요청일", "")),
                                "name": str(row.get("제품명(고객용)", "")),
                                "color": str(row.get("색상", "")),
                                "stock": int(row.get("수량", 0)),
                                "delivery_to": str(row.get("납품처", "")),
                                "delivery_contact": str(row.get("납품연락처", "")),
                                "delivery_address": str(row.get("납품주소", "")),
                                "note": str(row.get("비고", "")),
                                "status": "발주접수"
                            }
                            
                            db.collection("orders").add(doc_data)
                            success_count += 1
                            progress_bar.progress((idx + 1) / len(df_upload))
                            
                        if success_count > 0:
                            st.success(f"✅ {success_count}건의 발주가 성공적으로 등록되었습니다.")
                        
                        if error_logs:
                            st.error(f"⚠️ {len(error_logs)}건의 오류가 발생했습니다.")
                            for log in error_logs:
                                st.write(log)
                                
                except Exception as e:
                    st.error(f"파일 처리 중 오류가 발생했습니다: {e}")

            st.divider()
            st.subheader("발주 내역 삭제 (다중 선택)")
            st.info("삭제할 항목을 선택(체크)한 후 하단의 삭제 버튼을 누르세요. (헤더의 체크박스로 전체 선택 가능)")

            # 삭제 대상 목록 가져오기
            del_docs = list(db.collection("orders").order_by("date", direction=firestore.Query.DESCENDING).stream())
            
            if del_docs:
                del_rows = []
                for doc in del_docs:
                    d = doc.to_dict()
                    d['id'] = doc.id
                    del_rows.append(d)
                
                df_del = pd.DataFrame(del_rows)

                # 날짜 포맷
                if 'date' in df_del.columns:
                    df_del['date'] = df_del['date'].apply(lambda x: x.strftime('%Y-%m-%d') if hasattr(x, 'strftime') else x)

                # 데이터프레임 표시 (다중 선택 활성화)
                selection = st.dataframe(
                    df_del,
                    column_config={
                        "id": None, # ID 숨김
                        "order_no": "발주번호", "date": "접수일", "customer": "발주처",
                        "name": "제품명", "stock": "수량", "status": "상태"
                    },
                    column_order=["order_no", "date", "customer", "name", "stock", "status"],
                    hide_index=True,
                    width="stretch",
                    on_select="rerun",
                    selection_mode="multi-row",
                    key=f"del_orders_selection_{st.session_state['del_orders_key']}"
                )
                
                # 선택된 행 삭제 처리
                if selection.selection.rows:
                    selected_indices = selection.selection.rows
                    selected_rows = df_del.iloc[selected_indices]
                    
                    if st.button(f"🗑️ 선택한 {len(selected_rows)}건 영구 삭제", type="primary"):
                        for idx, row in selected_rows.iterrows():
                            db.collection("orders").document(row['id']).delete()
                        st.success(f"{len(selected_rows)}건이 삭제되었습니다.")
                        st.session_state["del_orders_key"] += 1
                        st.rerun()
            else:
                st.info("삭제할 발주 내역이 없습니다.")
            return

    st.write("조건을 설정하여 발주 내역을 조회하고 관리합니다.")

    # 메뉴 첫 진입 시 기본 검색 조건 설정
    if "search_performed" not in st.session_state:
        st.session_state["search_performed"] = True
        today = datetime.date.today()
        st.session_state["search_date_range"] = [today - datetime.timedelta(days=30), today]
        st.session_state["search_filter_status_new"] = []
        st.session_state["search_filter_customer"] = ""

    with st.form("search_form"):
        c1, c2, c3 = st.columns(3)
        # 날짜 범위 선택 (기본값: 세션에 저장된 값 사용)
        date_range = c1.date_input("조회 기간", st.session_state.get("search_date_range"), format="YYYY-MM-DD")
        # 상세 공정 상태 목록 추가
        status_options = ["발주접수", "제직대기", "제직중", "제직완료", "염색중", "염색완료", "봉제중", "봉제완료", "출고완료"]
        
        # 초기값: 이전에 검색한 값이 있으면 유지, 없으면 빈 리스트 (전체 조회)
        default_status = st.session_state.get("search_filter_status_new")
        # 에러 방지: 현재 옵션에 있는 값만 필터링 (코드가 바뀌었을 때를 대비)
        valid_default = [x for x in default_status if x in status_options]
        
        filter_status = c2.multiselect("진행 상태 (비워두면 전체)", status_options, default=valid_default)
        filter_customer = c3.text_input("발주처 검색", value=st.session_state.get("search_filter_customer"))
        
        search_btn = st.form_submit_button("🔍 조회하기")

    # 검색 버튼 클릭 시 세션에 검색 조건 저장 (새로고침 되어도 유지되도록)
    if search_btn:
        st.session_state["search_performed"] = True
        st.session_state["search_date_range"] = date_range
        st.session_state["search_filter_status_new"] = filter_status
        st.session_state["search_filter_customer"] = filter_customer
        st.rerun()

    if st.session_state.get("search_performed"):
        # 저장된 검색 조건 사용
        s_date_range = st.session_state["search_date_range"]
        
        # [NEW] 목록 갱신을 위한 키 초기화
        if "order_status_key" not in st.session_state:
            st.session_state["order_status_key"] = 0

        s_filter_status = st.session_state["search_filter_status_new"]
        s_filter_customer = st.session_state["search_filter_customer"]

        # 날짜 필터링을 위해 datetime 변환
        start_date = datetime.datetime.combine(s_date_range[0], datetime.time.min)
        end_date = datetime.datetime.combine(s_date_range[1], datetime.time.max) if len(s_date_range) > 1 else datetime.datetime.combine(s_date_range[0], datetime.time.max)

        docs = db.collection("orders").where("date", ">=", start_date).where("date", "<=", end_date).order_by("date", direction=firestore.Query.DESCENDING).stream()

    # 데이터를 리스트로 변환
        rows = []
        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            
            # [수정] 마스터 완료 상태를 일반 '제직완료'로 표시
            if d.get('status') == "제직완료(Master)":
                d['status'] = "제직완료"
            
            if 'date' in d and d['date']:
                d['date'] = d['date'].strftime("%Y-%m-%d")
            rows.append(d)
            
        if rows:
            df = pd.DataFrame(rows)
            
            # [수정] 발주번호(order_no) 컬럼이 없으면 강제로 생성 (빈 값)
            if 'order_no' not in df.columns:
                df['order_no'] = ""
            
            # [NEW] 납품요청일 날짜 포맷팅 (YYYY-MM-DD)
            if 'delivery_req_date' in df.columns:
                df['delivery_req_date'] = pd.to_datetime(df['delivery_req_date'], errors='coerce').dt.strftime('%Y-%m-%d').fillna('')
            
            # 상태 및 거래처 필터 (메모리 상에서 2차 필터)
            if s_filter_status:
                df = df[df['status'].isin(s_filter_status)]
            if s_filter_customer:
                df = df[df['customer'].str.contains(s_filter_customer, na=False)]
            
            # 컬럼명 한글 매핑
            col_map = {
                "product_code": "제품코드", "order_no": "발주번호", "status": "상태", "date": "접수일", "customer": "발주처",
                "name": "제품명", "product_type": "제품종류", "weaving_type": "제품종류(구)",
                "yarn_type": "사종", "color": "색상", "weight": "중량",
                "size": "사이즈", "stock": "수량",
                "delivery_req_date": "납품요청일", "delivery_to": "납품처",
                "delivery_contact": "납품연락처", "delivery_address": "납품주소",
                "note": "비고"
            }

            # 컬럼 순서 변경 (발주번호 -> 상태 -> 접수일 ...)
            display_cols = ["product_code", "order_no", "status", "date", "customer", "name", "stock", "product_type", "weaving_type", "yarn_type", "color", "weight", "size", "delivery_req_date", "delivery_to", "delivery_contact", "delivery_address", "note"]
            final_cols = [c for c in display_cols if c in df.columns] # 실제 존재하는 컬럼만 선택
            
            # 화면 표시용 데이터프레임 (한글 컬럼 적용)
            df_display = df[final_cols].rename(columns=col_map)
            
            # [NEW] 테이블 위 작업 영역 (상태변경, 수정버튼 등)
            action_placeholder = st.container()

            # --- 수정/삭제를 위한 테이블 선택 기능 ---
            st.write("🔽 목록에서 수정하거나 제직대기로 보낼 행을 선택(체크)하세요. (다중 선택 가능)")
            selection = st.dataframe(
                df_display, 
                width="stretch", 
                hide_index=True,  # 맨 왼쪽 순번(0,1,2..) 숨기기
                on_select="rerun", # 선택 시 리런
                selection_mode="multi-row", # 다중 선택 가능으로 변경
                height=700, # [수정] 목록 높이 확대 (약 20행)
                key=f"order_status_list_{st.session_state['order_status_key']}" # [수정] 동적 키 적용
            )
            
            # [MOVED] 작업 영역 로직 (테이블 상단)
            if selection.selection.rows:
                selected_indices = selection.selection.rows
                selected_rows = df.iloc[selected_indices]
                
                with action_placeholder:
                    # 1. 제직 지시 (발주접수 -> 제직대기)
                    # 선택된 항목 중 '발주접수' 상태인 것만 필터링
                    valid_to_weaving = selected_rows[selected_rows['status'] == '발주접수']
                    
                    if not valid_to_weaving.empty:
                        with st.expander(f"제직 지시 ({len(valid_to_weaving)}건)", expanded=True):
                            st.write(f"선택한 항목 중 **'발주접수' 상태인 {len(valid_to_weaving)}건**을 **'제직대기'**로 변경합니다.")
                            if st.button("선택 항목 제직대기로 발송", type="primary", key="btn_batch_weaving"):
                                for idx, row in valid_to_weaving.iterrows():
                                    db.collection("orders").document(row['id']).update({"status": "제직대기"})
                                st.success(f"{len(valid_to_weaving)}건이 제직대기 상태로 변경되었습니다.")
                                st.session_state["order_status_key"] += 1
                                st.rerun()
                    
                    # 2. 상세 수정 바로가기 (단일 선택 시)
                    if len(selection.selection.rows) == 1:
                        st.markdown("""
                            <a href="#edit_detail_section" style="text-decoration: none;">
                                <div style="
                                    display: inline-block;
                                    padding: 0.5rem 1rem;
                                    background-color: #f0f2f6;
                                    color: #31333F;
                                    border-radius: 0.5rem;
                                    border: 1px solid #d6d6d8;
                                    font-weight: 500;
                                    text-align: center;
                                    cursor: pointer;
                                    margin-bottom: 10px;
                                ">
                                    선택한 내역 상세 수정 (화면 아래로 이동)
                                </div>
                            </a>
                        """, unsafe_allow_html=True)
            
            # 버튼 영역 (엑셀 다운로드 + 인쇄)
            btn_c1, btn_c2 = st.columns([1, 1])
            
            # 엑셀 다운로드 (xlsx)
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_display.to_excel(writer, index=False)
                
            btn_c1.download_button(
                label="💾 엑셀(.xlsx) 다운로드",
                data=buffer.getvalue(),
                file_name='발주현황.xlsx',
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )

            # 인쇄 옵션 설정
            with st.expander("인쇄 옵션 설정"):
                po_c1, po_c2, po_c3, po_c4 = st.columns(4)
                p_title = po_c1.text_input("제목", value="발주 현황 리스트")
                p_title_size = po_c2.number_input("제목 크기(px)", value=24, step=1)
                p_body_size = po_c3.number_input("본문 글자 크기(px)", value=11, step=1)
                p_padding = po_c4.number_input("셀 여백(px)", value=6, step=1)
                
                po_c5, po_c6, po_c7 = st.columns(3)
                p_show_date = po_c5.checkbox("출력일시 표시", value=True)
                p_date_pos = po_c6.selectbox("일시 위치", ["Right", "Left", "Center"], index=0)
                p_date_size = po_c7.number_input("일시 글자 크기(px)", value=12, step=1)
                
                st.caption("페이지 여백 (mm)")
                po_c8, po_c9, po_c10, po_c11 = st.columns(4)
                p_m_top = po_c8.number_input("상단", value=15, step=1)
                p_m_bottom = po_c9.number_input("하단", value=15, step=1)
                p_m_left = po_c10.number_input("좌측", value=15, step=1)
                p_m_right = po_c11.number_input("우측", value=15, step=1)
                
                st.divider()
                st.markdown("###### 컬럼 설정 (순서 변경 및 너비 지정)")
                st.caption("💡 아래 버튼을 사용하여 컬럼 순서를 변경하세요.")

                # [수정] 인쇄 선택용 컬럼명을 한글로 변환
                final_cols_kr = [col_map.get(c, c) for c in final_cols]
                
                # 세션 상태에 설정 데이터프레임 초기화 및 동기화
                if "print_settings_df" not in st.session_state:
                    # 초기값 생성 (기본 너비 0 = 자동)
                    init_data = []
                    for i, col in enumerate(final_cols_kr):
                        init_data.append({"출력": True, "컬럼명": col, "너비(px)": 0, "순서": i+1})
                    st.session_state["print_settings_df"] = pd.DataFrame(init_data)
                
                # 현재 컬럼과 동기화 (새로운 컬럼이 생기면 추가)
                curr_df = st.session_state["print_settings_df"]
                existing_cols = set(curr_df["컬럼명"].tolist())
                new_cols = [c for c in final_cols_kr if c not in existing_cols]
                
                if new_cols:
                    max_order = curr_df["순서"].max() if not curr_df.empty else 0
                    new_rows = []
                    for i, col in enumerate(new_cols):
                        new_rows.append({"출력": True, "컬럼명": col, "너비(px)": 0, "순서": max_order + i + 1})
                    if new_rows:
                        curr_df = pd.concat([curr_df, pd.DataFrame(new_rows)], ignore_index=True)
                        st.session_state["print_settings_df"] = curr_df
                
                # 화면 표시를 위해 순서대로 정렬
                df_editor_view = st.session_state["print_settings_df"].sort_values("순서")
                
                # 에디터 갱신을 위한 버전 관리
                if "print_settings_ver" not in st.session_state:
                    st.session_state["print_settings_ver"] = 0

                # 데이터 에디터 표시
                edited_df = st.data_editor(
                    df_editor_view,
                    column_config={
                        "출력": st.column_config.CheckboxColumn("출력", width="small"),
                        "컬럼명": st.column_config.TextColumn("컬럼명", disabled=True),
                        "너비(px)": st.column_config.NumberColumn("너비(px)", min_value=0, max_value=500, width="small", help="0으로 설정하면 자동 너비가 적용됩니다."),
                        "순서": st.column_config.NumberColumn("순서", width="small", disabled=True), # [수정] 직접 입력 방지
                    },
                    hide_index=True,
                    width="stretch",
                    key=f"print_settings_editor_{st.session_state['print_settings_ver']}"
                )
                
                # 변경사항 저장 (리런 시 반영됨)
                st.session_state["print_settings_df"] = edited_df

                # [NEW] 순서 변경 도구 (위/아래 이동 및 초기화)
                c_move1, c_move2, c_move3, c_move4, c_move5 = st.columns([3, 1.3, 1.3, 2, 1.3])
                
                current_cols_ordered = df_editor_view["컬럼명"].tolist()
                
                # 선택 상태 유지를 위한 index 계산
                default_ix = 0
                if "last_target_col" in st.session_state and st.session_state["last_target_col"] in current_cols_ordered:
                    default_ix = current_cols_ordered.index(st.session_state["last_target_col"])

                with c_move1:
                    target_col = st.selectbox("이동할 컬럼 선택", current_cols_ordered, index=default_ix, label_visibility="collapsed", key="sb_col_move")
                
                with c_move2:
                    if st.button("⬆️ 위로 한칸", help="위로 이동"):
                        st.session_state["last_target_col"] = target_col
                        df = st.session_state["print_settings_df"].sort_values("순서").reset_index(drop=True)
                        try:
                            idx = df[df["컬럼명"] == target_col].index[0]
                            if idx > 0:
                                df.iloc[idx], df.iloc[idx-1] = df.iloc[idx-1].copy(), df.iloc[idx].copy()
                                df["순서"] = range(1, len(df) + 1)
                                st.session_state["print_settings_df"] = df
                                st.session_state["print_settings_ver"] += 1
                                st.rerun()
                        except: pass

                with c_move3:
                    if st.button("⬇️ 아래로 한칸", help="아래로 이동"):
                        st.session_state["last_target_col"] = target_col
                        df = st.session_state["print_settings_df"].sort_values("순서").reset_index(drop=True)
                        try:
                            idx = df[df["컬럼명"] == target_col].index[0]
                            if idx < len(df) - 1:
                                df.iloc[idx], df.iloc[idx+1] = df.iloc[idx+1].copy(), df.iloc[idx].copy()
                                df["순서"] = range(1, len(df) + 1)
                                st.session_state["print_settings_df"] = df
                                st.session_state["print_settings_ver"] += 1
                                st.rerun()
                        except: pass
                
                with c_move5:
                    if st.button("🔄 초기화", help="순서 초기화"):
                        if "last_target_col" in st.session_state:
                            del st.session_state["last_target_col"]
                        df = st.session_state["print_settings_df"].sort_values("순서").reset_index(drop=True)
                        
                        # [수정] 초기화 로직 개선: 기본 컬럼 순서(final_cols_kr)대로 순서값 재할당
                        df = st.session_state["print_settings_df"]
                        order_map = {col: i+1 for i, col in enumerate(final_cols_kr)}
                        df["순서"] = df["컬럼명"].map(order_map).fillna(999)
                        df = df.sort_values("순서").reset_index(drop=True)
                        df["순서"] = range(1, len(df) + 1)
                        
                        st.session_state["print_settings_df"] = df
                        st.session_state["print_settings_ver"] += 1
                        st.rerun()
                
                # 인쇄 로직에 사용할 변수 추출
                # 출력 체크된 것만, 순서대로 정렬
                print_target = edited_df[edited_df["출력"]].sort_values("순서")
                # 현재 데이터프레임에 존재하는 컬럼만 선택 (KeyError 방지)
                p_selected_cols = [c for c in print_target["컬럼명"].tolist() if c in final_cols_kr]
                # 너비 정보 딕셔너리
                p_widths = dict(zip(print_target["컬럼명"], print_target["너비(px)"]))
                
                # 스타일 설정
                p_nowrap = st.checkbox("텍스트 줄바꿈 방지 (한 줄 표시)", value=False)

            # 인쇄 버튼 (HTML 생성 후 새 창 열기 방식 흉내)
            if btn_c2.button("🖨️ 바로 인쇄하기"):
                print_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                date_align = p_date_pos.lower()
                date_display = "block" if p_show_date else "none"
                
                # [수정] 선택된 컬럼만 필터링
                print_df = df_display[p_selected_cols]
                
                # [수정] CSS 생성 (줄바꿈 방지 및 너비 지정)
                custom_css = ""
                if p_nowrap:
                    custom_css += "td { white-space: nowrap; }\n"
                
                for i, col in enumerate(p_selected_cols):
                    w = p_widths.get(col, 0)
                    if w > 0:
                        # nth-child는 1부터 시작
                        custom_css += f"table tr th:nth-child({i+1}), table tr td:nth-child({i+1}) {{ width: {w}px; min-width: {w}px; }}\n"

                # [수정] body에 onload를 추가하고, 화면에는 보이지 않도록 CSS 수정
                print_html = f"""
                    <html>
                    <head>
                        <title>{p_title}</title>
                        <style>
                            @page {{ margin: {p_m_top}mm {p_m_right}mm {p_m_bottom}mm {p_m_left}mm; }}
                            body {{ font-family: 'Malgun Gothic', sans-serif; padding: 0; margin: 0; }}
                            h2 {{ text-align: center; margin-bottom: 5px; font-size: {p_title_size}px; }}
                            .info {{ text-align: {date_align}; font-size: {p_date_size}px; margin-bottom: 10px; color: #555; display: {date_display}; }}
                            table {{ width: 100%; border-collapse: collapse; font-size: {p_body_size}px; }}
                            th, td {{ border: 1px solid #444; padding: {p_padding}px 4px; text-align: center; }}
                            th {{ background-color: #f0f0f0; font-weight: bold; }}
                            @media screen {{ body {{ display: none; }} }}
                            {custom_css}
                        </style>
                    </head>
                    <body onload="window.print();">
                        <h2>{p_title}</h2>
                        <div class="info">출력일시: {print_date}</div>
                        {print_df.to_html(index=False, border=1)}
                    </body>
                    </html>
                """
                # 보이지 않는 컴포넌트로 HTML을 렌더링하여 스크립트(window.print) 실행
                st.components.v1.html(print_html, height=0, width=0)

            # --- 상세 수정 (단일 선택 시에만) ---
            if len(selection.selection.rows) == 1:
                # 스크롤 이동을 위한 앵커
                st.markdown('<div id="edit_detail_section"></div>', unsafe_allow_html=True)
                st.divider()
                
                selected_idx = selection.selection.rows[0]
                # 선택된 행의 데이터 가져오기 (df는 필터링된 상태일 수 있으므로 iloc 사용)
                sel_row = df.iloc[selected_idx]
                sel_id = sel_row['id']
                
                # 제직기 명칭 매핑을 위한 데이터 가져오기
                machine_map = {}
                try:
                    m_docs = db.collection("machines").stream()
                    for m in m_docs:
                        md = m.to_dict()
                        machine_map[md.get('machine_no')] = md.get('name')
                except: pass

                # [NEW] 상세 이력 뷰
                st.subheader(f"상세 이력 정보: {sel_row['name']} ({sel_row['order_no']})")
                
                def fmt_dt(val):
                    if pd.isna(val) or val == "" or val is None: return "-"
                    if isinstance(val, pd.Timestamp): return val.strftime("%Y-%m-%d %H:%M")
                    if isinstance(val, datetime.datetime): return val.strftime("%Y-%m-%d %H:%M")
                    return str(val)[:16]
                
                def fmt_date(val):
                    if pd.isna(val) or val == "" or val is None: return "-"
                    if isinstance(val, pd.Timestamp): return val.strftime("%Y-%m-%d")
                    if isinstance(val, datetime.datetime): return val.strftime("%Y-%m-%d")
                    return str(val)[:10]

                def fmt_num(val, unit=""):
                    try: return f"{int(val):,}{unit}"
                    except: return "-"
                
                def fmt_float(val, unit=""):
                    try: return f"{float(val):,.1f}{unit}"
                    except: return "-"
                
                def fmt_money(val):
                    try: return f"{int(val):,}원"
                    except: return "-"

                c_p1, c_p2, c_p3, c_p4 = st.columns(4)
                
                with c_p1:
                    st.markdown("##### 제직 공정")
                    if sel_row.get('weaving_start_time'):
                        m_no = sel_row.get('machine_no')
                        try:
                            m_no_int = int(m_no) if pd.notna(m_no) else None
                            m_name = machine_map.get(m_no_int, f"{m_no_int}호기" if m_no_int is not None else "-")
                        except:
                            m_name = str(m_no)
                            
                        st.caption("제직 설정 및 결과")
                        st.text(f"제직기    : {m_name}")
                        st.text(f"시작일시  : {fmt_dt(sel_row.get('weaving_start_time'))}")
                        st.text(f"제직롤수  : {fmt_num(sel_row.get('weaving_roll_count'), '롤')}")
                        st.markdown("---")
                        st.text(f"완료일시  : {fmt_dt(sel_row.get('weaving_end_time'))}")
                        st.text(f"생산매수  : {fmt_num(sel_row.get('real_stock'), '장')}")
                        st.text(f"중량(g)   : {fmt_num(sel_row.get('real_weight'), 'g')}")
                        st.text(f"생산중량  : {fmt_float(sel_row.get('prod_weight_kg'), 'kg')}")
                        st.text(f"평균중량  : {fmt_float(sel_row.get('avg_weight'), 'g')}")
                    else:
                        st.info("대기 중")

                with c_p2:
                    st.markdown("##### 염색 공정")
                    if sel_row.get('dyeing_out_date'):
                        st.caption("염색 출고 및 입고")
                        st.text(f"염색업체  : {sel_row.get('dyeing_partner')}")
                        st.text(f"출고일자  : {fmt_date(sel_row.get('dyeing_out_date'))}")
                        st.text(f"출고중량  : {fmt_float(sel_row.get('dyeing_out_weight'), 'kg')}")
                        st.text(f"색상정보  : {sel_row.get('dyeing_color_name')} ({sel_row.get('dyeing_color_code')})")
                        st.text(f"비고      : {sel_row.get('dyeing_note')}")
                        st.markdown("---")
                        st.text(f"입고일자  : {fmt_date(sel_row.get('dyeing_in_date'))}")
                        st.text(f"입고중량  : {fmt_float(sel_row.get('dyeing_in_weight'), 'kg')}")
                        st.text(f"염색단가  : {fmt_money(sel_row.get('dyeing_unit_price'))}")
                        st.text(f"염색금액  : {fmt_money(sel_row.get('dyeing_amount'))}")
                    else:
                        st.info("대기 중")

                with c_p3:
                    st.markdown("##### 봉제 공정")
                    if sel_row.get('sewing_start_date'):
                        st.caption("봉제 작업 및 결과")
                        st.text(f"봉제업체  : {sel_row.get('sewing_partner')}")
                        st.text(f"작업구분  : {sel_row.get('sewing_type')}")
                        st.text(f"시작일자  : {fmt_date(sel_row.get('sewing_start_date'))}")
                        st.markdown("---")
                        st.text(f"완료일자  : {fmt_date(sel_row.get('sewing_end_date'))}")
                        st.text(f"완료수량  : {fmt_num(sel_row.get('stock'), '장')}")
                        st.text(f"불량수량  : {fmt_num(sel_row.get('sewing_defect_qty'), '장')}")
                        if sel_row.get('sewing_type') == "외주봉제":
                            st.text(f"봉제단가  : {fmt_money(sel_row.get('sewing_unit_price'))}")
                            st.text(f"봉제금액  : {fmt_money(sel_row.get('sewing_amount'))}")
                    else:
                        st.info("대기 중")

                with c_p4:
                    st.markdown("##### 출고/배송")
                    if sel_row.get('shipping_date'):
                        st.caption("출고 정보")
                        st.text(f"출고일시  : {fmt_dt(sel_row.get('shipping_date'))}")
                        st.text(f"출고방법  : {sel_row.get('shipping_method')}")
                        st.text(f"납품처    : {sel_row.get('delivery_to')}")
                        st.text(f"연락처    : {sel_row.get('delivery_contact')}")
                        st.text(f"주소      : {sel_row.get('delivery_address')}")
                    else:
                        st.info("미출고")
                
                st.divider()
                
                # 수정 폼을 위해 기초 데이터 다시 로드
                product_types_coded = get_common_codes("product_types", [])
                product_type_names = [item['name'] for item in product_types_coded]
                customer_list = get_partners("발주처")

                with st.expander("발주 내역 상세 수정", expanded=False):
                    with st.form("edit_order_form"):
                        st.write(f"선택된 발주건: **{sel_row['customer']} - {sel_row['name']}**")
                        
                        # [추가] 상태 변경 기능 (관리자용 강제 변경)
                        st.markdown("##### 관리자 상태 변경 (실수 복구용)")
                        status_options = ["발주접수", "제직대기", "제직중", "제직완료", "염색출고", "염색중", "염색완료", "봉제중", "봉제완료", "출고완료"]
                        e_status = st.selectbox("현재 상태", status_options, index=status_options.index(sel_row['status']) if sel_row['status'] in status_options else 0)
                        st.divider()

                        # 모든 필드 수정 가능하도록 배치
                        ec1, ec2, ec4 = st.columns(3)
                        e_customer = ec1.selectbox("발주처", customer_list, index=customer_list.index(sel_row['customer']) if sel_row['customer'] in customer_list else 0)
                        e_name = ec2.text_input("제품명", value=sel_row['name'])
                        e_stock = ec4.number_input("수량", value=int(sel_row['stock']), step=10)

                        ec5, ec6, ec7, ec8 = st.columns(4)
                        current_product_type = sel_row.get('product_type', sel_row.get('weaving_type'))
                        e_product_type = ec5.selectbox("제품종류", product_type_names, index=product_type_names.index(current_product_type) if current_product_type in product_type_names else 0)
                        e_yarn = ec6.text_input("사종", value=sel_row.get('yarn_type', ''))
                        e_color = ec7.text_input("색상", value=sel_row.get('color', ''))
                        e_weight = ec8.number_input("중량", value=int(sel_row.get('weight', 0)), step=10)

                        ec9, ec10, ec11 = st.columns(3)
                        e_size = ec9.text_input("사이즈", value=sel_row.get('size', ''))
                        
                        # [수정] 날짜 파싱 오류 방지 (시간 정보가 포함된 경우 처리)
                        try:
                            if sel_row.get('delivery_req_date'):
                                default_date = pd.to_datetime(str(sel_row['delivery_req_date'])).date()
                            else:
                                default_date = datetime.date.today()
                        except:
                            default_date = datetime.date.today()
                            
                        e_del_date = ec10.date_input("납품요청일", default_date, format="YYYY-MM-DD")
                        e_note = ec11.text_input("특이사항", value=sel_row.get('note', ''))
                        
                        ec12, ec13, ec14 = st.columns(3)
                        e_del_to = ec12.text_input("납품처", value=sel_row.get('delivery_to', ''))
                        e_del_contact = ec13.text_input("납품연락처", value=sel_row.get('delivery_contact', ''))
                        e_del_addr = ec14.text_input("납품주소", value=sel_row.get('delivery_address', ''))

                        if st.form_submit_button("수정 저장"):
                            db.collection("orders").document(sel_id).update({
                                "status": e_status, # 상태 변경 반영
                                "customer": e_customer,
                                "name": e_name,
                                "stock": e_stock,
                                "product_type": e_product_type,
                                "yarn_type": e_yarn,
                                "color": e_color,
                                "weight": e_weight,
                                "size": e_size,
                                "delivery_req_date": str(e_del_date),
                                "note": e_note,
                                "delivery_to": e_del_to,
                                "delivery_contact": e_del_contact,
                                "delivery_address": e_del_addr
                            })
                            st.success("수정되었습니다.")
                            st.session_state["order_status_key"] += 1
                            st.rerun()
                    
                    # 삭제 확인 및 처리 (폼 밖에서 처리)
                    st.divider()
                    if st.button("🗑️ 이 발주건 삭제", type="primary", key="btn_del_req"):
                        st.session_state["delete_confirm_id"] = sel_id
                    
                    if st.session_state.get("delete_confirm_id") == sel_id:
                        st.warning("정말로 삭제하시겠습니까? (복구 불가)")
                        col_conf1, col_conf2 = st.columns(2)
                        if col_conf1.button("✅ 예, 삭제합니다", key="btn_del_yes"):
                            db.collection("orders").document(sel_id).delete()
                            st.session_state["delete_confirm_id"] = None
                            st.success("삭제되었습니다.")
                            st.session_state["order_status_key"] += 1
                            st.rerun()
                        if col_conf2.button("❌ 취소", key="btn_del_no"):
                            st.session_state["delete_confirm_id"] = None
                            st.rerun()
            elif len(selection.selection.rows) > 1:
                st.info("ℹ️ 상세 수정은 한 번에 하나의 행만 선택했을 때 가능합니다. (상단 일괄 변경 기능 사용 가능)")
            else:
                st.info("👆 위 목록에서 수정하거나 상태를 변경할 행을 선택해주세요.")

        else:
            st.info("해당 기간에 조회된 데이터가 없습니다.")