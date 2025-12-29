import streamlit as st
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import datetime
import json
import pandas as pd
import io

# 1. 화면 기본 설정 (제목 등)
st.set_page_config(page_title="타올 생산 현황 관리", layout="wide")
st.title("🏭 세안타올 생산관리 현황")

# 2. 데이터베이스 연결 (아까 받은 열쇠 사용)
# 이미 연결되어 있다면 건너뛰고, 안 되어 있을 때만 연결합니다.
@st.cache_resource
def get_db():
    if not firebase_admin._apps:
        cred = None
        # 방법 1: Streamlit Cloud의 비밀 금고(Secrets) 시도
        try:
            if "FIREBASE_KEY" in st.secrets:
                secret_val = st.secrets["FIREBASE_KEY"]
                if isinstance(secret_val, str):
                    key_dict = json.loads(secret_val)
                else:
                    key_dict = dict(secret_val)
                cred = credentials.Certificate(key_dict)
        except:
            # 로컬 환경이라 secrets가 없는 경우 무시하고 넘어감
            pass

        # 방법 2: 로컬 환경이거나 비밀 금고가 없으면 내 컴퓨터 파일 사용
        if cred is None:
            # 방법 2: 로컬 환경이거나 비밀 금고가 없으면 내 컴퓨터 파일 사용
            cred = credentials.Certificate("serviceAccountKey.json")
            
        firebase_admin.initialize_app(cred)
    return firestore.client()

db = get_db()

# --- 로그인 기능 추가 ---
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = True   # 개발 편의를 위해 True로 설정
    st.session_state["role"] = "admin"     # 개발 편의를 위해 admin으로 설정

# 개발 중 로그인 비활성화 (나중에 주석 해제하여 다시 사용)
# if not st.session_state["logged_in"]:
#     st.subheader("로그인")
#     login_id = st.text_input("아이디", placeholder="admin 또는 guest")
#     login_pw = st.text_input("비밀번호", type="password", placeholder="1234")
#     
#     if st.button("로그인"):
#         # 예시를 위해 하드코딩된 계정 사용 (실제로는 DB에서 확인 권장)
#         if login_id == "admin" and login_pw == "1234":
#             st.session_state["logged_in"] = True
#             st.session_state["role"] = "admin"
#             st.rerun()
#         elif login_id == "guest" and login_pw == "1234":
#             st.session_state["logged_in"] = True
#             st.session_state["role"] = "guest"
#             st.rerun()
#         else:
#             st.error("아이디 또는 비밀번호를 확인하세요.")
#     st.stop()  # 로그인 전에는 아래 내용을 보여주지 않음

# 3. [왼쪽 사이드바] 상품 등록 기능
with st.sidebar:
    st.write(f"환영합니다, **{st.session_state['role']}**님!")
    # if st.button("로그아웃"):
    #     st.session_state["logged_in"] = False
    #     st.session_state["role"] = None
    #     st.rerun()
    st.divider()
    
    # 메뉴 선택 기능 추가
    if "current_menu" not in st.session_state:
        st.session_state["current_menu"] = "발주서접수"

    st.subheader("메뉴 선택")
    with st.expander("🏭 생산관리", expanded=True):
        if st.button("📑 발주서접수", use_container_width=True):
            st.session_state["current_menu"] = "발주서접수"
            st.rerun()
        if st.button("📊 발주현황", use_container_width=True):
            st.session_state["current_menu"] = "발주현황"
            st.rerun()
        if st.button("🧵 제직현황", use_container_width=True):
            st.session_state["current_menu"] = "제직현황"
            st.rerun()
        if st.button("🎨 염색현황", use_container_width=True):
            st.session_state["current_menu"] = "염색현황"
            st.rerun()
        if st.button("🪡 봉제현황", use_container_width=True):
            st.session_state["current_menu"] = "봉제현황"
            st.rerun()
        if st.button("🚚 출고현황", use_container_width=True):
            st.session_state["current_menu"] = "출고현황"
            st.rerun()
        if st.button("📦 현재고현황", use_container_width=True):
            st.session_state["current_menu"] = "현재고현황"
            st.rerun()

    with st.expander("⚙️ 기초정보관리", expanded=True):
        if st.button("🏢 거래처관리", use_container_width=True):
            st.session_state["current_menu"] = "거래처관리"
            st.rerun()
        if st.button("🏭 제직기관리", use_container_width=True):
            st.session_state["current_menu"] = "제직기관리"
            st.rerun()
        if st.button("📝 기초코드관리", use_container_width=True):
            st.session_state["current_menu"] = "기초코드관리"
            st.rerun()
            
    menu = st.session_state["current_menu"]

# --- 공통 함수: 기초 코드 가져오기 ---
def get_common_codes(code_type, default_values):
    doc_ref = db.collection("settings").document("codes")
    doc = doc_ref.get()
    if doc.exists:
        data = doc.to_dict()
        return data.get(code_type, default_values)
    return default_values

# --- 공통 함수: 거래처 목록 가져오기 ---
def get_partners(partner_type=None):
    query = db.collection("partners")
    if partner_type:
        query = query.where("type", "==", partner_type)
    docs = query.stream()
    partners = []
    for doc in docs:
        p = doc.to_dict()
        partners.append(p.get("name"))
    return partners

# 4. [메인 화면] 메뉴별 기능 구현
if menu == "발주서접수":
    st.header("📑 발주서 접수")
    st.info("신규 발주서를 시스템에 등록합니다.")
    
    if st.session_state["role"] == "admin":
        # 기초 데이터 불러오기
        weaving_types = get_common_codes("weaving_types", ["30수 연사", "40수 코마사", "무지", "자카드", "기타"])
        customer_list = get_partners("발주처")

        with st.form("order_form", clear_on_submit=True):
            st.subheader("기본 발주 정보")
            c1, c2, c3 = st.columns(3)
            order_date = c1.date_input("발주접수일", datetime.date.today(), format="YYYY-MM-DD")
            # 거래처 목록이 없으면 텍스트 입력, 있으면 선택박스
            if customer_list:
                customer = c2.selectbox("발주처 선택", customer_list)
            else:
                customer = c2.text_input("발주처 (기초정보관리에서 거래처를 등록하세요)")
            delivery_req_date = c3.date_input("납품요청일", datetime.date.today() + datetime.timedelta(days=7), format="YYYY-MM-DD")

            st.subheader("제품 상세 정보")
            c1, c3, c4 = st.columns(3)
            name = c1.text_input("제품명 (타올 종류)")
            weaving_type = c3.selectbox("제직타입", weaving_types)
            yarn_type = c4.text_input("사종", placeholder="예:30, 40")
            
            c1, c2, c3, c4 = st.columns(4)
            color = c1.text_input("색상")
            weight = c2.number_input("중량(g)", min_value=0, step=10)
            size = c3.text_input("사이즈", placeholder="예: 40x80")
            stock = c4.number_input("수량(장)", min_value=0, step=10)

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
                    
                    # 해당 월의 가장 마지막 발주번호 조회
                    last_docs = db.collection("inventory")\
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
                        "order_no": order_no,
                        "date": datetime.datetime.combine(order_date, datetime.time.min), # 날짜 형식을 datetime으로 변환
                        "customer": customer,
                        "delivery_req_date": str(delivery_req_date),
                        "name": name,
                        "weaving_type": weaving_type,
                        "yarn_type": yarn_type,
                        "color": color,
                        "weight": weight,
                        "size": size,
                        "stock": stock,
                        "delivery_to": delivery_to,
                        "delivery_contact": delivery_contact,
                        "delivery_address": delivery_address,
                        "note": note,
                        "status": "발주접수" # 초기 상태
                    }
                    db.collection("inventory").add(doc_data)
                    st.success(f"발주번호 [{order_no}] 접수 완료!")
                    st.rerun()
                else:
                    st.error("제품명과 발주처는 필수 입력 항목입니다.")
    else:
        st.info("관리자만 발주를 등록할 수 있습니다.")

elif menu == "발주현황":
    st.header("📊 발주 현황")
    st.write("조건을 설정하여 발주 내역을 조회하고 관리합니다.")

    with st.form("search_form"):
        c1, c2, c3 = st.columns(3)
        # 날짜 범위 선택 (기본값: 최근 30일)
        today = datetime.date.today()
        date_range = c1.date_input("조회 기간", [today - datetime.timedelta(days=30), today], format="YYYY-MM-DD")
        # 상세 공정 상태 목록 추가
        status_options = ["발주접수", "제직대기", "제직중", "제직완료", "염색출고", "염색중", "염색완료", "봉제중", "봉제완료", "출고완료"]
        
        # 초기값: 이전에 검색한 값이 있으면 유지, 없으면 빈 리스트 (전체 조회)
        default_status = st.session_state.get("search_filter_status_new", [])
        # 에러 방지: 현재 옵션에 있는 값만 필터링 (코드가 바뀌었을 때를 대비)
        valid_default = [x for x in default_status if x in status_options]
        
        filter_status = c2.multiselect("진행 상태 (비워두면 전체)", status_options, default=valid_default)
        filter_customer = c3.text_input("발주처 검색")
        
        search_btn = st.form_submit_button("🔍 조회하기")

    # 검색 버튼 클릭 시 세션에 검색 조건 저장 (새로고침 되어도 유지되도록)
    if search_btn:
        st.session_state["search_performed"] = True
        st.session_state["search_date_range"] = date_range
        st.session_state["search_filter_status_new"] = filter_status
        st.session_state["search_filter_customer"] = filter_customer

    if st.session_state.get("search_performed"):
        # 저장된 검색 조건 사용
        s_date_range = st.session_state["search_date_range"]
        s_filter_status = st.session_state["search_filter_status_new"]
        s_filter_customer = st.session_state["search_filter_customer"]

        # 날짜 필터링을 위해 datetime 변환
        start_date = datetime.datetime.combine(s_date_range[0], datetime.time.min)
        end_date = datetime.datetime.combine(s_date_range[1], datetime.time.max) if len(s_date_range) > 1 else datetime.datetime.combine(s_date_range[0], datetime.time.max)

        docs = db.collection("inventory").where("date", ">=", start_date).where("date", "<=", end_date).order_by("date", direction=firestore.Query.DESCENDING).stream()

    # 데이터를 리스트로 변환
        rows = []
        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            
            # [수정] 롤별 상세 내역(하위 문서)은 발주현황 목록에서 제외
            if 'parent_id' in d:
                continue
                
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
            
            # 상태 및 거래처 필터 (메모리 상에서 2차 필터)
            if s_filter_status:
                df = df[df['status'].isin(s_filter_status)]
            if s_filter_customer:
                df = df[df['customer'].str.contains(s_filter_customer, na=False)]
            
            # 컬럼명 한글 매핑
            col_map = {
                "order_no": "발주번호", "status": "상태", "date": "접수일", "customer": "발주처",
                "name": "제품명", "weaving_type": "제직타입",
                "yarn_type": "사종", "color": "색상", "weight": "중량",
                "size": "사이즈", "stock": "수량",
                "delivery_req_date": "납품요청일", "delivery_to": "납품처",
                "delivery_contact": "납품연락처", "delivery_address": "납품주소",
                "note": "비고"
            }

            # 컬럼 순서 변경 (발주번호 -> 상태 -> 접수일 ...)
            display_cols = ["order_no", "status", "date", "customer", "name", "stock", "weaving_type", "yarn_type", "color", "weight", "size", "delivery_req_date", "delivery_to", "delivery_contact", "delivery_address", "note"]
            final_cols = [c for c in display_cols if c in df.columns] # 실제 존재하는 컬럼만 선택
            
            # 화면 표시용 데이터프레임 (한글 컬럼 적용)
            df_display = df[final_cols].rename(columns=col_map)
            
            # --- 수정/삭제를 위한 테이블 선택 기능 ---
            st.write("🔽 목록에서 수정할 행을 선택(체크)하세요.")
            selection = st.dataframe(
                df_display, 
                use_container_width=True, 
                hide_index=True,  # 맨 왼쪽 순번(0,1,2..) 숨기기
                on_select="rerun", # 선택 시 리런
                selection_mode="single-row" # 한 번에 한 줄만 선택
            )
            
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
            with st.expander("🖨️ 인쇄 옵션 설정"):
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

            # 인쇄 버튼 (HTML 생성 후 새 창 열기 방식 흉내)
            if btn_c2.button("🖨️ 인쇄 페이지 열기"):
                print_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                date_align = p_date_pos.lower()
                date_display = "block" if p_show_date else "none"
                
                print_html = f"""
                    <html>
                    <head>
                        <title>{p_title}</title>
                        <style>
                            body {{ font-family: 'Malgun Gothic', sans-serif; padding: 20px; }}
                            @page {{ margin: {p_m_top}mm {p_m_right}mm {p_m_bottom}mm {p_m_left}mm; }}
                            body {{ font-family: 'Malgun Gothic', sans-serif; padding: 0; margin: 0; }}
                            h2 {{ text-align: center; margin-bottom: 5px; font-size: {p_title_size}px; }}
                            .info {{ text-align: {date_align}; font-size: {p_date_size}px; margin-bottom: 10px; color: #555; display: {date_display}; }}
                            table {{ width: 100%; border-collapse: collapse; font-size: {p_body_size}px; }}
                            th, td {{ border: 1px solid #444; padding: {p_padding}px 4px; text-align: center; }}
                            th {{ background-color: #f0f0f0; font-weight: bold; }}
                            @media print {{ .no-print {{ display: none; }} }}
                        </style>
                    </head>
                    <body>
                        <h2>{p_title}</h2>
                        <div class="info">출력일시: {print_date}</div>
                        <div class="no-print" style="text-align:right; margin-bottom:10px;">
                            <button onclick="window.print()" style="padding:8px 15px; font-size:14px; cursor:pointer; background-color:#4CAF50; color:white; border:none; border-radius:4px;">🖨️ 인쇄하기</button>
                        </div>
                        {df_display.to_html(index=False, border=1)}
                    </body>
                    </html>
                """
                # 인쇄용 HTML을 화면 하단에 렌더링 (스크립트로 인해 인쇄창이 뜸)
                st.components.v1.html(print_html, height=600, scrolling=True)

            # --- 수정 및 삭제 기능 (발주접수 상태만) ---
            st.divider()
            st.subheader("🛠️ 발주 내역 수정 및 관리")
            
            # 테이블에서 선택된 행이 있는지 확인
            if selection.selection.rows:
                selected_idx = selection.selection.rows[0]
                # 선택된 행의 데이터 가져오기 (df는 필터링된 상태일 수 있으므로 iloc 사용)
                sel_row = df.iloc[selected_idx]
                sel_id = sel_row['id']
                
                # 수정 폼을 위해 기초 데이터 다시 로드
                weaving_types = get_common_codes("weaving_types", ["30수 연사", "무지", "기타"])
                customer_list = get_partners("발주처")

                with st.form("edit_order_form"):
                    st.write(f"선택된 발주건: **{sel_row['customer']} - {sel_row['name']}**")
                    
                    # [추가] 상태 변경 기능 (관리자용 강제 변경)
                    st.markdown("##### ⚠️ 관리자 상태 변경 (실수 복구용)")
                    status_options = ["발주접수", "제직대기", "제직중", "제직완료", "염색출고", "염색중", "염색완료", "봉제중", "봉제완료", "출고완료"]
                    e_status = st.selectbox("현재 상태", status_options, index=status_options.index(sel_row['status']) if sel_row['status'] in status_options else 0)
                    st.divider()

                    # 모든 필드 수정 가능하도록 배치
                    ec1, ec2, ec4 = st.columns(3)
                    e_customer = ec1.selectbox("발주처", customer_list, index=customer_list.index(sel_row['customer']) if sel_row['customer'] in customer_list else 0)
                    e_name = ec2.text_input("제품명", value=sel_row['name'])
                    e_stock = ec4.number_input("수량", value=int(sel_row['stock']), step=10)

                    ec5, ec6, ec7, ec8 = st.columns(4)
                    e_weaving = ec5.selectbox("제직타입", weaving_types, index=weaving_types.index(sel_row['weaving_type']) if sel_row['weaving_type'] in weaving_types else 0)
                    e_yarn = ec6.text_input("사종", value=sel_row.get('yarn_type', ''))
                    e_color = ec7.text_input("색상", value=sel_row.get('color', ''))
                    e_weight = ec8.number_input("중량", value=int(sel_row.get('weight', 0)), step=10)

                    ec9, ec10, ec11 = st.columns(3)
                    e_size = ec9.text_input("사이즈", value=sel_row.get('size', ''))
                    e_del_date = ec10.date_input("납품요청일", datetime.datetime.strptime(sel_row['delivery_req_date'], "%Y-%m-%d").date() if sel_row.get('delivery_req_date') else datetime.date.today(), format="YYYY-MM-DD")
                    e_note = ec11.text_input("특이사항", value=sel_row.get('note', ''))
                    
                    ec12, ec13, ec14 = st.columns(3)
                    e_del_to = ec12.text_input("납품처", value=sel_row.get('delivery_to', ''))
                    e_del_contact = ec13.text_input("납품연락처", value=sel_row.get('delivery_contact', ''))
                    e_del_addr = ec14.text_input("납품주소", value=sel_row.get('delivery_address', ''))

                    if st.form_submit_button("수정 저장"):
                        db.collection("inventory").document(sel_id).update({
                            "status": e_status, # 상태 변경 반영
                            "customer": e_customer,
                            "name": e_name,
                            "stock": e_stock,
                            "weaving_type": e_weaving,
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
                        st.rerun()
                
                # 삭제 확인 및 처리 (폼 밖에서 처리)
                st.divider()
                if st.button("🗑️ 이 발주건 삭제", type="primary", key="btn_del_req"):
                    st.session_state["delete_confirm_id"] = sel_id
                
                if st.session_state.get("delete_confirm_id") == sel_id:
                    st.warning("정말로 삭제하시겠습니까? (복구 불가)")
                    col_conf1, col_conf2 = st.columns(2)
                    if col_conf1.button("✅ 예, 삭제합니다", key="btn_del_yes"):
                        db.collection("inventory").document(sel_id).delete()
                        st.session_state["delete_confirm_id"] = None
                        st.success("삭제되었습니다.")
                        st.rerun()
                    if col_conf2.button("❌ 취소", key="btn_del_no"):
                        st.session_state["delete_confirm_id"] = None
                        st.rerun()
            else:
                st.info("👆 위 목록에서 수정할 행을 선택해주세요.")

        else:
            st.info("해당 기간에 조회된 데이터가 없습니다.")
    else:
        st.write("조건을 설정하여 발주 내역을 조회합니다.")

        st.info("조회 기간을 선택하고 조회 버튼을 눌러주세요.")

elif menu == "현재고현황":
    st.header("📦 현재고 현황")

    # 새로고침 버튼
    if st.button("목록 새로고침"):
        st.rerun()

    # 데이터베이스에서 모든 데이터 가져오기
    docs = list(db.collection("inventory").order_by("date", direction=firestore.Query.DESCENDING).stream())

    if not docs:
        st.info("아직 등록된 데이터가 없습니다.")

    # 헤더
    col1, col2, col3, col4 = st.columns([3, 1, 2, 2])
    col1.write("**제품명 (구분)**")
    col2.write("**수량**")
    col3.write("**등록일**")
    col4.write("**관리**")

    for doc in docs:
        item = doc.to_dict()
        doc_id = doc.id
        
        with st.container():
            c1, c2, c3, c4 = st.columns([3, 1, 2, 2])
            c1.write(f"{item.get('name')}")
            c2.write(f"{item.get('stock')}개")
            c3.write(item.get('date').strftime("%Y-%m-%d") if item.get('date') else "")
            
            with c4:
                if st.session_state["role"] == "admin":
                    btn1, btn2, btn3 = st.columns(3)
                    if btn1.button("➕", key=f"add_{doc_id}"):
                        db.collection("inventory").document(doc_id).update({"stock": item.get('stock') + 1})
                        st.rerun()
                    if btn2.button("➖", key=f"sub_{doc_id}"):
                        if item.get('stock', 0) > 0:
                            db.collection("inventory").document(doc_id).update({"stock": item.get('stock') - 1})
                            st.rerun()
                    if btn3.button("🗑️", key=f"del_{doc_id}", help="삭제"):
                        db.collection("inventory").document(doc_id).delete()
                        st.rerun()
                else:
                    st.caption("조회 전용")
        st.divider()

elif menu == "제직현황":
    st.header("🧵 제직 현황")
    st.info("발주된 건을 확인하고 제직 작업을 지시하거나, 완료된 건을 염색 공정으로 넘깁니다.")

    # 1. 제직기 가동 현황 (Dashboard)
    st.subheader("🏭 제직기 가동 현황")
    
    # 제직기 설정 가져오기
    machines_docs = list(db.collection("machines").order_by("machine_no").stream())
    if not machines_docs:
        # 설정이 없으면 기본 1~9호대 가상 데이터 사용 (호환성 유지)
        machines_data = [{"machine_no": i, "name": f"{i}호대", "model": "", "note": ""} for i in range(1, 10)]
    else:
        machines_data = [d.to_dict() for d in machines_docs]
    
    # 현재 가동 중인 제직기 정보 가져오기
    busy_machines = {}
    running_docs = db.collection("inventory").where("status", "==", "제직중").stream()
    for doc in running_docs:
        d = doc.to_dict()
        m_no = d.get("machine_no")
        if m_no:
            busy_machines[str(m_no)] = d
            
    # 제직기 상태 표시 (한 줄에 5개씩 자동 줄바꿈)
    cols_per_row = 5
    for i in range(0, len(machines_data), cols_per_row):
        cols = st.columns(cols_per_row)
        for j in range(cols_per_row):
            if i + j < len(machines_data):
                m = machines_data[i+j]
                m_no = str(m['machine_no'])
                m_name = m['name']
                m_desc = f"{m.get('model','')}\n{m.get('note','')}".strip()
                
                with cols[j]:
                    if m_no in busy_machines:
                        item = busy_machines[m_no]
                        roll_cnt = item.get('weaving_roll_count', 0)
                        # 진행률 표시
                        cur_roll = item.get('completed_rolls', 0) + 1
                        st.error(f"**{m_name}**\n\n{item.get('name')}\n({cur_roll}/{roll_cnt}롤)")
                    else:
                        st.success(f"**{m_name}**\n\n대기중\n\n{m_desc}")
    
    st.divider()

    # 5개의 탭으로 분리하여 관리
    tab_waiting, tab_weaving, tab_done, tab_worklog, tab_prodlog = st.tabs([
        "📋 제직대기 목록", "🏭 제직중 목록", "✅ 제직완료 목록", "✍️ 작업일지", "📄 생산일지"
    ])

    # --- 1. 제직대기 탭 ---
    with tab_waiting:
        st.subheader("제직 대기 목록")
        # '발주접수', '제직대기' 상태인 건 가져오기
        docs = db.collection("inventory").where("status", "in", ["발주접수", "제직대기"]).stream()
        rows = []
        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            rows.append(d)
        
        if rows:
            df = pd.DataFrame(rows)
            # 날짜 포맷팅
            if 'date' in df.columns:
                df['date'] = df['date'].apply(lambda x: x.strftime('%Y-%m-%d') if not pd.isnull(x) and hasattr(x, 'strftime') else x)
            
            col_map = {
                "order_no": "발주번호", "status": "상태", "customer": "발주처", "name": "제품명", 
                "weaving_type": "제직타입", "yarn_type": "사종", "color": "색상", 
                "stock": "수량", "weight": "중량", "size": "사이즈", "date": "접수일"
            }
            display_cols = ["order_no", "status", "customer", "name", "stock", "weaving_type", "yarn_type", "color", "weight", "size", "date"]
            final_cols = [c for c in display_cols if c in df.columns]
            
            st.write("🔽 제직기를 배정할 항목을 선택하세요.")
            # key="df_waiting" 추가로 사이드바 먹통 현상 해결
            selection = st.dataframe(df[final_cols].rename(columns=col_map), use_container_width=True, on_select="rerun", selection_mode="single-row", key="df_waiting")
            
            if selection.selection.rows:
                idx = selection.selection.rows[0]
                sel_row = df.iloc[idx]
                sel_id = sel_row['id']
                
                st.divider()
                st.markdown(f"### 🚀 제직기 배정: **{sel_row['name']}**")
                with st.form("weaving_start_form"):
                    c1, c2, c3, c4 = st.columns(4)
                    
                    # 제직기 선택 (사용 중인 것은 표시)
                    m_options = []
                    for m in machines_data:
                        m_no = str(m['machine_no'])
                        m_name = m['name']
                        if m_no in busy_machines:
                            m_options.append(f"{m_no}:{m_name} (사용중)")
                        else:
                            m_options.append(f"{m_no}:{m_name}")
                    
                    s_machine = c1.selectbox("제직기 선택", m_options)
                    s_date = c2.date_input("시작일자", datetime.date.today(), format="YYYY-MM-DD")
                    s_time = c3.time_input("시작시간", datetime.datetime.now().time())
                    s_roll = c4.number_input("제직롤수량", min_value=1, step=1)
                    
                    if st.form_submit_button("제직 시작"):
                        sel_m_no = s_machine.split(":")[0]
                        if sel_m_no in busy_machines:
                            st.error(f"⛔ 해당 제직기는 이미 작업 중입니다!")
                        else:
                            start_dt = datetime.datetime.combine(s_date, s_time)
                            db.collection("inventory").document(sel_id).update({
                                "status": "제직중",
                                "machine_no": int(sel_m_no),
                                "weaving_start_time": start_dt,
                                "weaving_roll_count": s_roll,
                                "completed_rolls": 0
                            })
                            st.success(f"제직을 시작합니다.")
                            st.rerun()
        else:
            st.info("대기 중인 작업이 없습니다.")

    # --- 2. 제직중 탭 ---
    with tab_weaving:
        st.subheader("제직중 목록")
        
        # [추가] 작업 결과 피드백 메시지 표시 (저장 후 리런되어도 메시지 유지)
        if st.session_state.get("weaving_msg"):
            st.success(st.session_state["weaving_msg"])
            st.session_state["weaving_msg"] = None
            
        docs = db.collection("inventory").where("status", "==", "제직중").stream()
        rows = []
        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            rows.append(d)
            
        if rows:
            df = pd.DataFrame(rows)
            if 'weaving_start_time' in df.columns:
                df['weaving_start_time'] = df['weaving_start_time'].apply(lambda x: x.strftime('%Y-%m-%d %H:%M') if not pd.isnull(x) and hasattr(x, 'strftime') else x)
            
            # 진행률 표시를 위해 컬럼 확보
            if 'completed_rolls' not in df.columns: df['completed_rolls'] = 0
            col_map = {
                "order_no": "발주번호", "machine_no": "제직기", "weaving_start_time": "시작시간",
                "customer": "발주처", "name": "제품명", "stock": "수량", "weaving_roll_count": "롤수"
            }
            display_cols = ["machine_no", "order_no", "customer", "name", "stock", "weaving_roll_count", "weaving_start_time"]
            final_cols = [c for c in display_cols if c in df.columns]
            
            st.write("🔽 완료 처리할 항목을 선택하세요.")
            # key="df_weaving" 추가
            selection = st.dataframe(df[final_cols].rename(columns=col_map), use_container_width=True, on_select="rerun", selection_mode="single-row", key="df_weaving")
            
            if selection.selection.rows:
                idx = selection.selection.rows[0]
                sel_row = df.iloc[idx]
                sel_id = sel_row['id']
                
                # 현재 진행 상황 계산
                cur_completed = int(sel_row.get('completed_rolls', 0)) if not pd.isna(sel_row.get('completed_rolls')) else 0
                total_rolls = int(sel_row.get('weaving_roll_count', 1)) if not pd.isna(sel_row.get('weaving_roll_count')) else 1
                next_roll_no = cur_completed + 1
                
                st.divider()
                st.markdown(f"### ✅ 제직 완료 처리: **{sel_row['name']}**")
                
                if total_rolls > 1:
                    st.info(f"📢 현재 **{total_rolls}롤 중 {next_roll_no}번째 롤** 작업 중입니다.")
                else:
                    st.info("📢 **단일 롤(1/1)** 작업 중입니다.")
                
                with st.form("weaving_complete_form"):
                    st.write("생산 실적을 입력하세요.")
                    c1, c2 = st.columns(2)
                    end_date = c1.date_input("제직완료일", datetime.date.today())
                    end_time = c2.time_input("완료시간", datetime.datetime.now().time())
                    
                    # 기본값 계산 (정수형 변환)
                    base_weight = int(sel_row.get('weight', 0)) if not pd.isna(sel_row.get('weight')) else 0
                    total_stock = int(sel_row.get('stock', 0)) if not pd.isna(sel_row.get('stock')) else 0
                    
                    # 이번 롤의 예상 생산량 (전체수량 / 롤수)
                    def_roll_stock = int(total_stock / total_rolls) if total_rolls > 0 else total_stock
                    
                    def_prod_kg = int((base_weight * def_roll_stock) / 1000) # kg 계산
                    def_avg_weight = base_weight

                    c3, c4 = st.columns(2)
                    # step=1, format="%d"로 소수점 제거 및 1단위 증감
                    real_weight = c3.number_input("중량(g)", value=base_weight, step=1, format="%d")
                    real_stock = c4.number_input("생산매수(장)", value=def_roll_stock, step=1, format="%d")
                    
                    c5, c6 = st.columns(2)
                    prod_weight_kg = c5.number_input("생산중량(kg)", value=def_prod_kg, step=1, format="%d")
                    avg_weight = c6.number_input("평균중량(g)", value=def_avg_weight, step=1, format="%d")
                    
                    if st.form_submit_button("제직 완료 저장"):
                        end_dt = datetime.datetime.combine(end_date, end_time)
                        
                        # 1. 롤 데이터 생성 (새 문서)
                        # 부모 문서의 데이터를 가져와서 복사
                        parent_doc = db.collection("inventory").document(sel_id).get().to_dict()
                        new_roll_doc = parent_doc.copy()
                        
                        new_roll_doc['status'] = "제직완료"
                        new_roll_doc['order_no'] = f"{parent_doc.get('order_no')}-{next_roll_no}" # 예: 2405001-1
                        new_roll_doc['parent_id'] = sel_id
                        new_roll_doc['roll_no'] = next_roll_no
                        new_roll_doc['weaving_end_time'] = end_dt
                        new_roll_doc['real_weight'] = real_weight
                        new_roll_doc['real_stock'] = real_stock
                        new_roll_doc['stock'] = real_stock # 중요: 이후 공정은 이 롤의 수량을 기준으로 함
                        new_roll_doc['prod_weight_kg'] = prod_weight_kg
                        new_roll_doc['avg_weight'] = avg_weight
                        
                        # 불필요한 필드 제거
                        if 'completed_rolls' in new_roll_doc: del new_roll_doc['completed_rolls']
                        if 'weaving_roll_count' in new_roll_doc: del new_roll_doc['weaving_roll_count']
                        
                        db.collection("inventory").add(new_roll_doc)
                        
                        # 2. 부모 문서 업데이트 (진행률 표시)
                        updates = {"completed_rolls": next_roll_no}
                        
                        # 마지막 롤이면 부모 문서는 '제직완료(Master)' 상태로 변경하여 목록에서 숨김
                        if next_roll_no >= total_rolls:
                            updates["status"] = "제직완료(Master)"
                            msg = f"🎉 마지막 롤({next_roll_no}/{total_rolls})까지 처리가 완료되었습니다!"
                        else:
                            msg = f"✅ {next_roll_no}번 롤 처리가 완료되었습니다. 이어서 {next_roll_no + 1}번 롤을 입력해주세요."
                        
                        db.collection("inventory").document(sel_id).update(updates)
                        
                        # 메시지를 세션에 저장하여 리런 후에도 보이게 함
                        st.session_state["weaving_msg"] = msg
                        st.rerun()
                
                if st.button("🚫 제직 취소 (대기로 되돌리기)", key="cancel_weaving"):
                    db.collection("inventory").document(sel_id).update({
                        "status": "발주접수",
                        "machine_no": firestore.DELETE_FIELD,
                        "weaving_start_time": firestore.DELETE_FIELD
                    })
                    st.rerun()
        else:
            st.info("현재 제직 중인 작업이 없습니다.")

    # --- 3. 제직완료 탭 ---
    with tab_done:
        st.subheader("제직 완료 목록")
        
        # 검색 조건 (기간 + 발주처)
        with st.form("search_weaving_done"):
            c1, c2 = st.columns([2, 1])
            today = datetime.date.today()
            s_date = c1.date_input("조회 기간 (완료일)", [today - datetime.timedelta(days=30), today])
            s_cust = c2.text_input("발주처 검색")
            st.form_submit_button("🔍 조회")

        # 날짜 범위 계산
        if len(s_date) == 2:
            start_dt = datetime.datetime.combine(s_date[0], datetime.time.min)
            end_dt = datetime.datetime.combine(s_date[1], datetime.time.max)
        else:
            start_dt = datetime.datetime.combine(s_date[0], datetime.time.min)
            end_dt = datetime.datetime.combine(s_date[0], datetime.time.max)

        docs = db.collection("inventory").where("status", "==", "제직완료").stream()
        rows = []
        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            
            # 1. 날짜 필터 (weaving_end_time 기준)
            w_end = d.get('weaving_end_time')
            if w_end:
                if w_end.tzinfo: w_end = w_end.replace(tzinfo=None) # 시간대 정보 제거 후 비교
                if not (start_dt <= w_end <= end_dt): continue
            else:
                continue
            
            # 2. 발주처 필터
            if s_cust and s_cust not in d.get('customer', ''):
                continue
                
            rows.append(d)
        
        # 최신순 정렬
        rows.sort(key=lambda x: x.get('weaving_end_time', datetime.datetime.min), reverse=True)

        if rows:
            df = pd.DataFrame(rows)
            if 'weaving_end_time' in df.columns:
                df['weaving_end_time'] = df['weaving_end_time'].apply(lambda x: x.strftime('%Y-%m-%d %H:%M') if not pd.isnull(x) and hasattr(x, 'strftime') else x)
            
            col_map = {
                "order_no": "발주번호", "machine_no": "제직기", "weaving_end_time": "완료시간",
                "customer": "발주처", "name": "제품명", 
                "real_stock": "생산매수", "real_weight": "중량(g)", 
                "prod_weight_kg": "생산중량(kg)", "avg_weight": "평균중량(g)",
                "roll_no": "롤번호"
            }
            display_cols = ["weaving_end_time", "machine_no", "order_no", "roll_no", "customer", "name", "real_stock", "real_weight", "prod_weight_kg", "avg_weight"]
            final_cols = [c for c in display_cols if c in df.columns]
            
            st.write("🔽 수정하거나 취소할 항목을 선택하세요.")
            selection = st.dataframe(
                df[final_cols].rename(columns=col_map), 
                use_container_width=True, 
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                key="df_done"
            )

            if selection.selection.rows:
                idx = selection.selection.rows[0]
                sel_row = df.iloc[idx]
                sel_id = sel_row['id']
                
                st.divider()
                st.markdown(f"### 🛠️ 제직 결과 수정: **{sel_row['name']} ({sel_row.get('roll_no', '?')}번 롤)**")
                
                with st.form("edit_weaving_done"):
                    c1, c2 = st.columns(2)
                    new_real_weight = c1.number_input("중량(g)", value=int(sel_row.get('real_weight', 0)), step=1, format="%d")
                    new_real_stock = c2.number_input("생산매수(장)", value=int(sel_row.get('real_stock', 0)), step=1, format="%d")
                    
                    c3, c4 = st.columns(2)
                    new_prod_kg = c3.number_input("생산중량(kg)", value=int(sel_row.get('prod_weight_kg', 0)), step=1, format="%d")
                    new_avg_weight = c4.number_input("평균중량(g)", value=int(sel_row.get('avg_weight', 0)), step=1, format="%d")
                    
                    if st.form_submit_button("수정 저장"):
                        db.collection("inventory").document(sel_id).update({
                            "real_weight": new_real_weight,
                            "real_stock": new_real_stock,
                            "stock": new_real_stock, # 이후 공정을 위해 재고 수량도 함께 업데이트
                            "prod_weight_kg": new_prod_kg,
                            "avg_weight": new_avg_weight
                        })
                        st.success("수정되었습니다.")
                        st.rerun()
                
                st.markdown("#### 🚫 제직 완료 취소 (삭제)")
                st.warning("이 롤 데이터를 삭제하고, 제직중 상태로 되돌립니다.")
                if st.button("🗑️ 이 롤 삭제하기 (취소)", type="primary"):
                    parent_id = sel_row.get('parent_id')
                    
                    # 1. 현재 롤 문서 삭제
                    db.collection("inventory").document(sel_id).delete()
                    
                    # 2. 부모 문서(제직중인 건) 상태 업데이트
                    if parent_id:
                        # 남은 형제 롤 개수 확인
                        siblings = db.collection("inventory").where("parent_id", "==", parent_id).where("status", "==", "제직완료").stream()
                        cnt = sum(1 for _ in siblings)
                        
                        db.collection("inventory").document(parent_id).update({
                            "completed_rolls": cnt,
                            "status": "제직중" # 마스터 완료 상태였더라도 다시 제직중으로 복귀
                        })
                    
                    st.success("삭제되었습니다. 제직중 목록에서 다시 작업할 수 있습니다.")
                    st.rerun()
        else:
            st.info("제직 완료된 내역이 없습니다.")

    # --- 4. 작업일지 탭 ---
    with tab_worklog:
        st.subheader("작업일지 작성 및 조회")
        
        # Part 1: 일지 작성
        with st.expander("➕ 작업일지 작성하기", expanded=True):
            with st.form("work_log_form"):
                c1, c2, c3 = st.columns(3)
                log_date = c1.date_input("작업일자", datetime.date.today())
                shift = c2.radio("근무조", ["주간", "야간"], horizontal=True)
                author = c3.text_input("작성자", value=st.session_state.get("role", ""))

                c1, c2 = st.columns(2)
                # 제직기 목록 가져오기
                m_options = [f"{m['machine_no']}:{m['name']}" for m in machines_data]
                machine_selection = c1.selectbox("관련 제직기", ["전체"] + m_options)
                log_time = c2.time_input("작성시간", datetime.datetime.now().time())
                
                content = st.text_area("작업 내용")
                
                handover_label = "야간근무자 전달사항" if shift == "주간" else "주간근무자 전달사항"
                handover_notes = st.text_area(handover_label, help="다음 근무조에게 전달할 내용을 입력하세요.")
                
                if st.form_submit_button("일지 저장"):
                    log_dt = datetime.datetime.combine(log_date, log_time)
                    machine_no_str = machine_selection.split(":")[0] if machine_selection != "전체" else "전체"
                    
                    # 1. 개별 로그 저장 (shift_logs 컬렉션)
                    db.collection("shift_logs").add({
                        "log_date": str(log_date),
                        "shift": shift,
                        "machine_no": machine_no_str,
                        "log_time": log_dt,
                        "content": content,
                        "author": author
                    })
                    
                    # 2. 전달사항 저장 (handover_notes 컬렉션)
                    if handover_notes:
                        note_key = "day_to_night_notes" if shift == "주간" else "night_to_day_notes"
                        db.collection("handover_notes").document(str(log_date)).set({
                            note_key: handover_notes
                        }, merge=True)
                    
                    st.success("작업일지가 저장되었습니다.")
                    st.rerun()

        # Part 2: 일지 조회
        st.divider()
        st.subheader("일지 조회 및 출력")
        
        c1, c2 = st.columns([1, 3])
        view_date = c1.date_input("조회할 날짜", datetime.date.today(), key="worklog_view_date")
        
        # 데이터 가져오기
        # Firestore 복합 인덱스 오류 방지를 위해 order_by 제거 후 Python에서 정렬
        log_docs = list(db.collection("shift_logs").where("log_date", "==", str(view_date)).stream())
        log_docs.sort(key=lambda x: x.to_dict().get('log_time', datetime.datetime.min))
        notes_doc = db.collection("handover_notes").document(str(view_date)).get()
        
        day_logs = []
        night_logs = []
        for doc in log_docs:
            log_data = doc.to_dict()
            if log_data['shift'] == '주간':
                day_logs.append(log_data)
            else:
                night_logs.append(log_data)
        
        notes_data = notes_doc.to_dict() if notes_doc.exists else {}
        
        # 인쇄 옵션 설정
        with st.expander("🖨️ 인쇄 옵션 설정"):
            po_c1, po_c2, po_c3, po_c4 = st.columns(4)
            p_title = po_c1.text_input("제목", value=f"작업 일지 ({view_date})", key="wl_title")
            p_title_size = po_c2.number_input("제목 크기(px)", value=24, step=1, key="wl_ts")
            p_body_size = po_c3.number_input("본문 글자 크기(px)", value=12, step=1, key="wl_bs")
            p_padding = po_c4.number_input("셀 여백(px)", value=6, step=1, key="wl_pad")
            
            po_c5, po_c6, po_c7 = st.columns(3)
            p_show_date = po_c5.checkbox("출력일시 표시", value=True, key="wl_sd")
            p_date_pos = po_c6.selectbox("일시 위치", ["Right", "Left", "Center"], index=0, key="wl_dp")
            p_date_size = po_c7.number_input("일시 글자 크기(px)", value=12, step=1, key="wl_ds")
            
            st.caption("페이지 여백 (mm)")
            po_c8, po_c9, po_c10, po_c11 = st.columns(4)
            p_m_top = po_c8.number_input("상단", value=15, step=1, key="wl_mt")
            p_m_bottom = po_c9.number_input("하단", value=15, step=1, key="wl_mb")
            p_m_left = po_c10.number_input("좌측", value=15, step=1, key="wl_ml")
            p_m_right = po_c11.number_input("우측", value=15, step=1, key="wl_mr")

        # 화면 표시 & 인쇄용 HTML 생성
        print_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        date_align = p_date_pos.lower()
        date_display = "block" if p_show_date else "none"

        style = f"""<style>
            @page {{ margin: {p_m_top}mm {p_m_right}mm {p_m_bottom}mm {p_m_left}mm; }}
            body {{ font-family: 'Malgun Gothic', sans-serif; padding: 0; margin: 0; }}
            table {{ width: 100%; border-collapse: collapse; margin-bottom: 15px; font-size: {p_body_size}px; }}
            th, td {{ border: 1px solid #444; padding: {p_padding}px; text-align: left; }}
            th {{ background-color: #f0f0f0; text-align: center; font-weight: bold; }}
            .header {{ text-align: center; margin-bottom: 10px; }}
            .header h2 {{ font-size: {p_title_size}px; margin: 0; }}
            .sub-header {{ text-align: {date_align}; font-size: {p_date_size}px; color: #555; margin-bottom: 10px; display: {date_display}; }}
            .section-title {{ font-size: {p_body_size + 2}px; font-weight: bold; margin-top: 20px; margin-bottom: 5px; border-bottom: 2px solid #ddd; padding-bottom: 3px; }}
            .note-box {{ border: 1px solid #444; padding: 10px; min-height: 60px; font-size: {p_body_size}px; }}
        </style>"""
        
        html_content = f"<html><head><title>{p_title}</title>{style}</head><body>"
        html_content += f"<div class='header'><h2>{p_title}</h2></div>"
        html_content += f"<div class='sub-header'>출력일시: {print_now}</div>"
        
        # 주간 섹션
        st.markdown("#### ☀️ 주간 작업")
        html_content += "<div class='section-title'>☀️ 주간 작업</div>"
        if day_logs:
            df_day = pd.DataFrame(day_logs)
            df_day['log_time'] = df_day['log_time'].apply(lambda x: x.strftime('%H:%M') if hasattr(x, 'strftime') else str(x)[11:16])
            st.dataframe(df_day[['log_time', 'machine_no', 'content', 'author']].rename(columns={'log_time':'시간','machine_no':'호기','content':'내용','author':'작성자'}), hide_index=True, use_container_width=True)
            html_content += df_day[['log_time', 'machine_no', 'content', 'author']].rename(columns={'log_time':'시간','machine_no':'호기','content':'내용','author':'작성자'}).to_html(index=False, border=1)
        else:
            st.info("기록 없음")
            html_content += "<p>기록 없음</p>"
            
        st.markdown("##### 📝 야간근무자 전달사항")
        d_note = notes_data.get('day_to_night_notes', '-')
        st.warning(d_note)
        html_content += f"<div class='section-title'>📝 야간근무자 전달사항</div><div class='note-box'>{d_note}</div>"

        st.divider()

        # 야간 섹션
        st.markdown("#### 🌙 야간 작업")
        html_content += "<div class='section-title'>🌙 야간 작업</div>"
        if night_logs:
            df_night = pd.DataFrame(night_logs)
            df_night['log_time'] = df_night['log_time'].apply(lambda x: x.strftime('%H:%M') if hasattr(x, 'strftime') else str(x)[11:16])
            st.dataframe(df_night[['log_time', 'machine_no', 'content', 'author']].rename(columns={'log_time':'시간','machine_no':'호기','content':'내용','author':'작성자'}), hide_index=True, use_container_width=True)
            html_content += df_night[['log_time', 'machine_no', 'content', 'author']].rename(columns={'log_time':'시간','machine_no':'호기','content':'내용','author':'작성자'}).to_html(index=False, border=1)
        else:
            st.info("기록 없음")
            html_content += "<p>기록 없음</p>"

        st.markdown("##### 📝 주간근무자 전달사항")
        n_note = notes_data.get('night_to_day_notes', '-')
        st.warning(n_note)
        html_content += f"<div class='section-title'>📝 주간근무자 전달사항</div><div class='note-box'>{n_note}</div>"
        html_content += "</body></html>"
        
        with c2:
            if st.button("🖨️ 작업일지 인쇄 미리보기"):
                print_view = html_content.replace("</body>", """
                    <div class="no-print" style="text-align:center; margin-top:20px; margin-bottom:20px;">
                        <button onclick="window.print()" style="padding:10px 20px; font-size:16px; cursor:pointer; background-color:#4CAF50; color:white; border:none; border-radius:4px;">🖨️ 인쇄하기</button>
                    </div>
                    <style>
                        @media print { .no-print { display: none; } }
                        body { margin: 0; padding: 20px; }
                    </style>
                    </body>
                """)
                st.components.v1.html(print_view, height=800, scrolling=True)

    # --- 5. 생산일지 탭 ---
    with tab_prodlog:
        st.subheader("일일 생산일지 조회")
        
        c1, c2 = st.columns([1, 3])
        prod_date = c1.date_input("조회일자", datetime.date.today(), key="prodlog_view_date")
        
        start_dt = datetime.datetime.combine(prod_date, datetime.time.min)
        end_dt = datetime.datetime.combine(prod_date, datetime.time.max)
        
        # Firestore 인덱스 오류 방지를 위해 status만 쿼리하고 날짜는 파이썬에서 필터링
        docs = db.collection("inventory").where("status", "==", "제직완료").stream()
        rows = []
        for doc in docs:
            d = doc.to_dict()
            w_end = d.get('weaving_end_time')
            if w_end:
                if w_end.tzinfo: w_end = w_end.replace(tzinfo=None)
                if start_dt <= w_end <= end_dt:
                    rows.append(d)
        
        if rows:
            df = pd.DataFrame(rows)
            df['weaving_end_time'] = df['weaving_end_time'].apply(lambda x: x.strftime('%H:%M') if not pd.isnull(x) and hasattr(x, 'strftime') else x)
            col_map = {"order_no": "발주번호", "machine_no": "제직기", "weaving_end_time": "완료시간", "customer": "발주처", "name": "제품명", "real_stock": "생산매수", "real_weight": "중량(g)", "prod_weight_kg": "생산중량(kg)", "avg_weight": "평균중량(g)", "roll_no": "롤번호"}
            display_cols = ["weaving_end_time", "machine_no", "order_no", "roll_no", "customer", "name", "real_stock", "real_weight", "prod_weight_kg", "avg_weight"]
            final_cols = [c for c in display_cols if c in df.columns]
            df_display = df[final_cols].rename(columns=col_map)
            st.markdown(f"### 📄 {prod_date} 생산일지")
            st.dataframe(df_display, hide_index=True, use_container_width=True)
            
            # 엑셀 다운로드 준비
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_display.to_excel(writer, index=False)
                
            # 인쇄 옵션 설정
            with st.expander("🖨️ 인쇄 옵션 설정"):
                po_c1, po_c2, po_c3, po_c4 = st.columns(4)
                p_title = po_c1.text_input("제목", value=f"{prod_date} 생산일지", key="pl_title")
                p_title_size = po_c2.number_input("제목 크기(px)", value=24, step=1, key="pl_ts")
                p_body_size = po_c3.number_input("본문 글자 크기(px)", value=11, step=1, key="pl_bs")
                p_padding = po_c4.number_input("셀 여백(px)", value=6, step=1, key="pl_pad")
                
                po_c5, po_c6, po_c7 = st.columns(3)
                p_show_date = po_c5.checkbox("출력일시 표시", value=True, key="pl_sd")
                p_date_pos = po_c6.selectbox("일시 위치", ["Right", "Left", "Center"], index=0, key="pl_dp")
                p_date_size = po_c7.number_input("일시 글자 크기(px)", value=12, step=1, key="pl_ds")
                
                st.caption("페이지 여백 (mm)")
                po_c8, po_c9, po_c10, po_c11 = st.columns(4)
                p_m_top = po_c8.number_input("상단", value=15, step=1, key="pl_mt")
                p_m_bottom = po_c9.number_input("하단", value=15, step=1, key="pl_mb")
                p_m_left = po_c10.number_input("좌측", value=15, step=1, key="pl_ml")
                p_m_right = po_c11.number_input("우측", value=15, step=1, key="pl_mr")

            print_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            date_align = p_date_pos.lower()
            date_display = "block" if p_show_date else "none"

            print_html = f"""<html><head><title>{p_title}</title>
            <style>
                body {{ font-family: 'Malgun Gothic', sans-serif; padding: 20px; }}
                @page {{ margin: {p_m_top}mm {p_m_right}mm {p_m_bottom}mm {p_m_left}mm; }}
                body {{ font-family: 'Malgun Gothic', sans-serif; padding: 0; margin: 0; }}
                h2 {{ text-align: center; margin-bottom: 5px; font-size: {p_title_size}px; }}
                .info {{ text-align: {date_align}; font-size: {p_date_size}px; margin-bottom: 10px; color: #555; display: {date_display}; }}
                table {{ width: 100%; border-collapse: collapse; font-size: {p_body_size}px; }}
                th, td {{ border: 1px solid #444; padding: {p_padding}px 4px; text-align: center; }}
                th {{ background-color: #f0f0f0; }}
            </style></head><body>
            <h2>{p_title}</h2>
            <div class="info">출력일시: {print_now}</div>
            {df_display.to_html(index=False)}</body></html>"""
            
            with c2:
                c2_1, c2_2 = st.columns(2)
                
                if c2_1.button("🖨️ 인쇄 미리보기"):
                    print_view = print_html.replace("</body>", """
                        <div class="no-print" style="text-align:center; margin-top:20px; margin-bottom:20px;">
                            <button onclick="window.print()" style="padding:10px 20px; font-size:16px; cursor:pointer; background-color:#4CAF50; color:white; border:none; border-radius:4px;">🖨️ 인쇄하기</button>
                        </div>
                        <style>
                            @media print { .no-print { display: none; } }
                            body { margin: 0; padding: 20px; }
                        </style>
                        </body>
                    """)
                    st.components.v1.html(print_view, height=800, scrolling=True)

                c2_2.download_button(
                    label="💾 엑셀 다운로드",
                    data=buffer.getvalue(),
                    file_name=f"생산일지_{prod_date}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
        else:
            st.info(f"{prod_date}에 완료된 생산 내역이 없습니다.")

elif menu == "염색현황":
    st.header("🎨 염색 현황")
    st.info("제직이 완료된 건을 염색 공장에서 작업하고 봉제 단계로 넘깁니다.")

    tab1, tab2 = st.tabs(["🏭 염색 작업 관리", "📋 염색 내역 조회"])

    with tab1:
        # '제직완료' (염색대기) 또는 '염색중' 상태인 건만 가져오기
        docs = db.collection("inventory").where("status", "in", ["제직완료", "염색중"]).stream()
        
        rows = []
        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            rows.append(d)
            
        rows.sort(key=lambda x: x['date'])
        
        if rows:
            for item in rows:
                with st.container():
                    c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 1, 2])
                    
                    status_color = "red" if item['status'] == "염색중" else "orange"
                    c1.markdown(f"**[{item['status']}]** :{status_color}[{item.get('order_no', '-')}]")
                    if item.get('roll_no'):
                        c1.caption(f"Roll No: {item.get('roll_no')}")
                    c1.write(f"📅 {item['date'].strftime('%Y-%m-%d')}")
                    
                    c2.write(f"**{item['customer']}**")
                    c2.write(f"{item['name']}")
                    
                    c3.write(f"{item['color']} / {item['stock']}장")
                    c3.write(f"{item['weight']}g")
                    
                    with c4.expander("🖨️ 지시서"):
                        st.markdown(f"""
                        <div style="border:1px solid #000; padding:10px; font-size:12px;">
                            <h3 style="text-align:center; margin:0;">염 색 지 시 서</h3>
                            <hr>
                            <p><strong>발주번호:</strong> {item.get('order_no')}</p>
                            <p><strong>발 주 처:</strong> {item['customer']}</p>
                            <p><strong>제 품 명:</strong> {item['name']}</p>
                            <p><strong>색    상:</strong> {item['color']}</p>
                            <p><strong>수    량:</strong> {item['stock']}장</p>
                            <p><strong>중    량:</strong> {item['weight']}g</p>
                            <p><strong>납품요청일:</strong> {item['delivery_req_date']}</p>
                            <p><strong>특이사항:</strong> {item.get('note', '-')}</p>
                        </div>
                        """, unsafe_allow_html=True)
                        st.caption("Ctrl+P로 인쇄")

                    if item['status'] == "제직완료":
                        if c5.button("염색 시작 ➡️", key=f"dye_start_{item['id']}"):
                            db.collection("inventory").document(item['id']).update({"status": "염색중"})
                            st.rerun()
                    elif item['status'] == "염색중":
                        if c5.button("염색 완료 (봉제로) ➡️", key=f"dye_end_{item['id']}"):
                            db.collection("inventory").document(item['id']).update({
                                "status": "봉제",
                                "dyeing_end_time": datetime.datetime.now()
                            })
                            st.rerun()
                    
                    st.divider()
        else:
            st.info("현재 염색 대기 중이거나 작업 중인 건이 없습니다.")

    with tab2:
        st.write("염색 공정 내역 조회 (추후 구현)")

elif menu == "봉제현황":
    st.header("🪡 봉제 현황")
    st.info("염색이 완료된 원단을 봉제하여 완제품으로 만듭니다.")
    
    tab1, tab2 = st.tabs(["🏭 봉제 작업 관리", "📋 봉제 내역 조회"])
    
    with tab1:
        # '봉제' (대기) 또는 '봉제중' 상태
        docs = db.collection("inventory").where("status", "in", ["봉제", "봉제중"]).stream()
        rows = []
        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            rows.append(d)
        rows.sort(key=lambda x: x.get('date', datetime.datetime.max))
        
        if rows:
            for item in rows:
                with st.container():
                    c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 1, 2])
                    status_color = "red" if item['status'] == "봉제중" else "orange"
                    c1.markdown(f"**[{item['status']}]** :{status_color}[{item.get('order_no', '-')}]")
                    c1.write(f"📅 {item.get('date', datetime.date.today()).strftime('%Y-%m-%d')}")
                    
                    c2.write(f"**{item.get('customer')}**")
                    c2.write(f"{item.get('name')}")
                    
                    c3.write(f"{item.get('color')} / {item.get('stock')}장")
                    
                    with c4.expander("🖨️ 지시서"):
                        st.markdown(f"""
                        <div style="border:1px solid #000; padding:10px; font-size:12px;">
                            <h3 style="text-align:center; margin:0;">봉 제 지 시 서</h3>
                            <hr>
                            <p><strong>발주번호:</strong> {item.get('order_no')}</p>
                            <p><strong>제 품 명:</strong> {item['name']}</p>
                            <p><strong>색상/수량:</strong> {item['color']} / {item['stock']}장</p>
                            <p><strong>특이사항:</strong> {item.get('note', '-')}</p>
                        </div>
                        """, unsafe_allow_html=True)
                        
                    if item['status'] == "봉제":
                        if c5.button("봉제 시작 ➡️", key=f"sew_start_{item['id']}"):
                            db.collection("inventory").document(item['id']).update({"status": "봉제중"})
                            st.rerun()
                    elif item['status'] == "봉제중":
                        if c5.button("봉제 완료 (출고대기) ➡️", key=f"sew_end_{item['id']}"):
                            db.collection("inventory").document(item['id']).update({
                                "status": "출고대기",
                                "sewing_end_time": datetime.datetime.now()
                            })
                            st.rerun()
                    st.divider()
        else:
            st.info("봉제 대기 중이거나 작업 중인 건이 없습니다.")
            
    with tab2:
        st.write("봉제 내역 조회 (추후 구현)")

elif menu == "출고현황":
    st.header("🚚 출고 현황")
    st.info("완성된 제품을 출고 처리하거나, 출고된 내역의 거래명세서를 발행합니다.")
    
    tab1, tab2 = st.tabs(["🚀 출고 대기 관리", "📋 출고 완료 내역 (명세서)"])
    
    with tab1:
        # '출고대기' 상태
        docs = db.collection("inventory").where("status", "==", "출고대기").stream()
        rows = []
        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            rows.append(d)
        rows.sort(key=lambda x: x.get('date', datetime.datetime.max))
        
        if rows:
            for item in rows:
                with st.container():
                    c1, c2, c3, c4 = st.columns([2, 2, 3, 2])
                    c1.markdown(f"**[{item['status']}]** :green[{item.get('order_no', '-')}]")
                    c2.write(f"**{item.get('customer')}**")
                    c3.write(f"{item.get('name')} ({item.get('stock')}장)")
                    
                    # 출고 방법 선택 및 완료 처리
                    with c4:
                        ship_method = st.selectbox("출고방법", ["택배", "화물", "용차", "직배송", "기타"], key=f"sm_{item['id']}")
                        if st.button("🚀 출고 완료 처리", key=f"ship_{item['id']}"):
                            db.collection("inventory").document(item['id']).update({
                                "status": "출고완료",
                                "shipping_date": datetime.datetime.now(),
                                "shipping_method": ship_method
                            })
                            st.success("출고 처리되었습니다.")
                            st.rerun()
                st.divider()
        else:
            st.info("출고 대기 중인 건이 없습니다.")

    with tab2:
        # '출고완료' 상태 조회
        docs = db.collection("inventory").where("status", "==", "출고완료").stream()
        rows = []
        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            rows.append(d)
            
        # 출고일(shipping_date) 기준 내림차순 정렬 (최신순)
        rows.sort(key=lambda x: x.get('shipping_date', datetime.datetime.min), reverse=True)
        
        if rows:
            for item in rows:
                with st.container():
                    c1, c2, c3, c4 = st.columns([2, 2, 3, 2])
                    ship_date = item.get('shipping_date').strftime('%Y-%m-%d') if item.get('shipping_date') else "-"
                    c1.write(f"📅 {ship_date}")
                    c2.write(f"**{item.get('customer')}**")
                    c3.write(f"{item.get('name')} ({item.get('stock')}장)")
                    
                    with c4.expander("🖨️ 거래명세서"):
                        # 거래명세서 HTML 디자인
                        invoice_html = f"""
                        <div style="border:2px solid #333; padding:20px; font-family:sans-serif; background-color:white; color:black;">
                            <h2 style="text-align:center; margin-bottom:30px; text-decoration:underline;">거 래 명 세 서</h2>
                            <table style="width:100%; margin-bottom:20px;">
                                <tr>
                                    <td style="width:50%;"><strong>공급받는자:</strong> {item.get('customer')} 귀하</td>
                                    <td style="width:50%; text-align:right;"><strong>일자:</strong> {ship_date}</td>
                                </tr>
                            </table>
                            <table style="width:100%; border-collapse:collapse; text-align:center; border:1px solid #333;">
                                <tr style="background-color:#eee;">
                                    <th style="border:1px solid #333; padding:8px;">품목</th>
                                    <th style="border:1px solid #333; padding:8px;">규격/사종</th>
                                    <th style="border:1px solid #333; padding:8px;">수량</th>
                                    <th style="border:1px solid #333; padding:8px;">비고</th>
                                </tr>
                                <tr>
                                    <td style="border:1px solid #333; padding:10px;">{item.get('name')}</td>
                                    <td style="border:1px solid #333; padding:10px;">{item.get('weaving_type')}</td>
                                    <td style="border:1px solid #333; padding:10px;">{item.get('stock')} 장</td>
                                    <td style="border:1px solid #333; padding:10px;">{item.get('note', '')}</td>
                                </tr>
                            </table>
                            <p style="margin-top:20px; text-align:center;">위와 같이 정히 영수(청구)함.</p>
                        </div>
                        """
                        st.markdown(invoice_html, unsafe_allow_html=True)
                        st.caption("Ctrl+P를 눌러 인쇄하세요.")
                st.divider()
        else:
            st.info("출고 완료된 내역이 없습니다.")

elif menu == "거래처관리":
    st.header("🏢 거래처 관리")
    
    tab1, tab2 = st.tabs(["➕ 거래처 등록", "📋 거래처 목록"])
    
    # 기초 코드에서 거래처 구분 가져오기
    partner_types = get_common_codes("partner_types", ["발주처", "염색업체", "봉제업체", "배송업체", "기타"])

    with tab1:
        with st.form("partner_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            p_type = c1.selectbox("거래처 구분", partner_types)
            p_name = c2.text_input("거래처명", placeholder="상호명 입력")
            
            c1, c2, c3 = st.columns(3)
            p_rep = c1.text_input("대표자명")
            p_biz_num = c2.text_input("사업자번호")
            p_item = c3.text_input("업태/종목")
            
            c1, c2, c3 = st.columns(3)
            p_phone = c1.text_input("전화번호")
            p_fax = c2.text_input("팩스번호")
            p_email = c3.text_input("이메일")
            
            p_address = st.text_input("주소")
            p_account = st.text_input("계좌번호")
            p_note = st.text_area("기타사항")
            
            if st.form_submit_button("거래처 저장"):
                if p_name:
                    db.collection("partners").add({
                        "type": p_type,
                        "name": p_name,
                        "rep_name": p_rep,
                        "biz_num": p_biz_num,
                        "item": p_item,
                        "phone": p_phone,
                        "fax": p_fax,
                        "email": p_email,
                        "address": p_address,
                        "account": p_account,
                        "note": p_note,
                        "reg_date": datetime.datetime.now()
                    })
                    st.success(f"{p_name} 저장 완료!")
                    st.rerun()
                else:
                    st.error("거래처명을 입력해주세요.")

    with tab2:
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
            all_cols = ["type", "name", "rep_name", "biz_num", "item", "phone", "fax", "email", "address", "account", "note"]
            
            # 데이터프레임에 없는 컬럼은 빈 문자열로 채움
            for col in all_cols:
                if col not in df.columns:
                    df[col] = ""
            
            # 컬럼명 한글로 변경
            col_map = {
                "type": "구분", "name": "거래처명", "rep_name": "대표자", 
                "biz_num": "사업자번호", "item": "업태/종목", "phone": "전화번호", 
                "fax": "팩스", "email": "이메일", "address": "주소", 
                "account": "계좌번호", "note": "비고"
            }
            st.dataframe(df[all_cols].rename(columns=col_map), use_container_width=True)
            
            # 2. 거래처 삭제 기능
            st.divider()
            st.subheader("🗑️ 거래처 삭제")
            
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

elif menu == "제직기관리":
    st.header("🏭 제직기 관리")
    
    tab1, tab2 = st.tabs(["➕ 제직기 등록", "📋 제직기 목록"])
    
    with tab1:
        st.subheader("제직기 등록 및 수정")
        st.info("호기 번호가 같으면 기존 정보가 수정(덮어쓰기)됩니다.")
        
        with st.form("add_machine_form_new"):
            c1, c2 = st.columns(2)
            new_no = c1.number_input("호기 번호 (No.)", min_value=1, step=1, help="정렬 순서 및 고유 ID로 사용됩니다.")
            new_name = c2.text_input("제직기 명칭", placeholder="예: 1호대")
            c3, c4 = st.columns(2)
            new_model = c3.text_input("모델명")
            new_note = c4.text_input("특이사항/메모")
            
            if st.form_submit_button("저장"):
                db.collection("machines").document(str(new_no)).set({
                    "machine_no": new_no,
                    "name": new_name,
                    "model": new_model,
                    "note": new_note
                })
                st.success("저장되었습니다.")
                st.rerun()

    with tab2:
        st.subheader("제직기 목록")
        machines_ref = db.collection("machines").order_by("machine_no")
        m_docs = list(machines_ref.stream())
        m_list = [d.to_dict() for d in m_docs]
        
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
            st.dataframe(pd.DataFrame(m_list), use_container_width=True, hide_index=True)
            
            st.divider()
            st.subheader("🗑️ 제직기 삭제")
            del_targets = st.multiselect("삭제할 제직기를 선택하세요", [f"{m['machine_no']}:{m['name']}" for m in m_list])
            if st.button("선택한 제직기 삭제"):
                for target in del_targets:
                    del_id = target.split(":")[0]
                    db.collection("machines").document(del_id).delete()
                st.success("삭제되었습니다.")
                st.rerun()

elif menu == "기초코드관리":
    st.header("⚙️ 기초 코드 관리")
    st.info("콤보박스에 표시될 항목들을 관리합니다.")
    
    code_tabs = st.tabs(["제직 타입", "거래처 구분"])
    
    # 코드 관리용 함수
    def manage_code(code_key, default_list, label):
        current_list = get_common_codes(code_key, default_list)
        st.write(f"현재 등록된 {label}: {', '.join(current_list)}")
        
        new_val = st.text_input(f"추가할 {label}", key=f"new_{code_key}")
        if st.button(f"추가", key=f"btn_add_{code_key}"):
            if new_val and new_val not in current_list:
                current_list.append(new_val)
                db.collection("settings").document("codes").set({code_key: current_list}, merge=True)
                st.success("추가되었습니다.")
                st.rerun()
        
        del_val = st.selectbox(f"삭제할 {label} 선택", ["선택하세요"] + current_list, key=f"del_{code_key}")
        if st.button(f"삭제", key=f"btn_del_{code_key}"):
            if del_val != "선택하세요":
                current_list.remove(del_val)
                db.collection("settings").document("codes").set({code_key: current_list}, merge=True)
                st.success("삭제되었습니다.")
                st.rerun()

    with code_tabs[0]: manage_code("weaving_types", ["30수 연사", "40수 코마사", "무지", "자카드", "기타"], "제직 타입")
    with code_tabs[1]: manage_code("partner_types", ["발주처", "염색업체", "봉제업체", "배송업체", "기타"], "거래처 구분")

else:
    st.header(f"🏗️ {menu}")
    st.info(f"'{menu}' 기능은 추후 업데이트될 예정입니다.")
