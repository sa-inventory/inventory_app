import streamlit as st
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import datetime
import json
import pandas as pd

# 1. 화면 기본 설정 (제목 등)
st.set_page_config(page_title="타올 생산 현황 관리", layout="wide")
st.title("🏭 세안타올 생산관리 현황")

# 2. 데이터베이스 연결 (아까 받은 열쇠 사용)
# 이미 연결되어 있다면 건너뛰고, 안 되어 있을 때만 연결합니다.
@st.cache_resource
def get_db():
    if not firebase_admin._apps:
        # 방법 1: Streamlit Cloud의 비밀 금고(Secrets)에 키가 있는지 확인
        if "FIREBASE_KEY" in st.secrets:
            secret_val = st.secrets["FIREBASE_KEY"]
            if isinstance(secret_val, str):
                key_dict = json.loads(secret_val)
            else:
                key_dict = dict(secret_val)
            cred = credentials.Certificate(key_dict)
        else:
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
    st.subheader("메뉴 선택")
    main_category = st.radio("카테고리", ["생산관리", "기초정보관리"])
    
    if main_category == "생산관리":
        menu = st.radio("업무 메뉴", 
            ["발주서접수", "제직현황", "염색현황", "봉제현황", "출고현황", "현재고현황"])
    else:
        menu = st.radio("관리 메뉴", ["거래처관리", "기초코드관리"])

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
    
    # 탭을 사용하여 '등록'과 '조회' 화면 분리
    tab1, tab2 = st.tabs(["📝 신규 발주 등록", "🔍 발주 현황 조회 및 관리"])
    
    with tab1:
        if st.session_state["role"] == "admin":
            # 기초 데이터 불러오기
            weaving_types = get_common_codes("weaving_types", ["30수 연사", "40수 코마사", "무지", "자카드", "기타"])
            customer_list = get_partners("발주처")

            with st.form("order_form", clear_on_submit=True):
                st.subheader("기본 발주 정보")
                c1, c2, c3 = st.columns(3)
                order_date = c1.date_input("발주접수일", datetime.date.today())
                # 거래처 목록이 없으면 텍스트 입력, 있으면 선택박스
                if customer_list:
                    customer = c2.selectbox("발주처 선택", customer_list)
                else:
                    customer = c2.text_input("발주처 (기초정보관리에서 거래처를 등록하세요)")
                delivery_req_date = c3.date_input("납품요청일", datetime.date.today() + datetime.timedelta(days=7))

                st.subheader("제품 상세 정보")
                c1, c3, c4 = st.columns(3)
                name = c1.text_input("제품명 (타올 종류)")
                weaving_type = c3.selectbox("제직타입", weaving_types)
                yarn_type = c4.text_input("사종", placeholder="예: 최고급 면사")
                
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
            st.info("관리자만 발주를 등록할 수 있습니다. 옆의 '발주 현황 조회' 탭을 이용해주세요.")

    with tab2:
        st.write("조건을 설정하여 발주 내역을 조회합니다.")

        with st.form("search_form"):
            c1, c2, c3 = st.columns(3)
            # 날짜 범위 선택 (기본값: 최근 30일)
            today = datetime.date.today()
            date_range = c1.date_input("조회 기간", [today - datetime.timedelta(days=30), today])
            # 상세 공정 상태 목록 추가
            status_options = ["발주접수", "제직대기", "제직중", "제직완료", "염색출고", "염색중", "염색완료", "봉제중", "봉제완료", "출고완료"]
            filter_status = c2.multiselect("진행 상태", status_options, default=["발주접수", "제직대기", "제직중"])
            filter_customer = c3.text_input("발주처 검색")
            
            search_btn = st.form_submit_button("🔍 조회하기")

        if search_btn:
            # 날짜 필터링을 위해 datetime 변환
            start_date = datetime.datetime.combine(date_range[0], datetime.time.min)
            end_date = datetime.datetime.combine(date_range[1], datetime.time.max) if len(date_range) > 1 else datetime.datetime.combine(date_range[0], datetime.time.max)

            docs = db.collection("inventory").where("date", ">=", start_date).where("date", "<=", end_date).order_by("date", direction=firestore.Query.DESCENDING).stream()

        # 데이터를 리스트로 변환
            rows = []
            for doc in docs:
                d = doc.to_dict()
                d['id'] = doc.id
                if 'date' in d and d['date']:
                    d['date'] = d['date'].strftime("%Y-%m-%d")
                rows.append(d)
                
            if rows:
                df = pd.DataFrame(rows)
                
                # 상태 및 거래처 필터 (메모리 상에서 2차 필터)
                if filter_status:
                    df = df[df['status'].isin(filter_status)]
                if filter_customer:
                    df = df[df['customer'].str.contains(filter_customer, na=False)]
                
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
                csv = df_display.to_csv(index=False).encode('utf-8-sig')
                btn_c1.download_button(
                    label="💾 엑셀 다운로드",
                    data=csv,
                    file_name='발주현황.csv',
                    mime='text/csv',
                )

                # 인쇄 버튼 (HTML 생성 후 새 창 열기 방식 흉내)
                if btn_c2.button("🖨️ 인쇄 페이지 열기"):
                    print_html = f"""
                        <html>
                        <head>
                            <title>발주현황 인쇄</title>
                            <style>
                                body {{ font-family: sans-serif; padding: 20px; }}
                                table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
                                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: center; }}
                                th {{ background-color: #f2f2f2; }}
                                @media print {{ .no-print {{ display: none; }} }}
                            </style>
                        </head>
                        <body>
                            <h2 style="text-align:center;">발주 현황 리스트</h2>
                            <div class="no-print" style="text-align:right; margin-bottom:10px;">
                                <button onclick="window.print()" style="padding:10px 20px; font-size:16px; cursor:pointer;">🖨️ 지금 인쇄하기 (Click)</button>
                            </div>
                            {df_display.to_html(index=False, border=1)}
                            <script>window.print();</script>
                        </body>
                        </html>
                    """
                    # 인쇄용 HTML을 화면 하단에 렌더링 (스크립트로 인해 인쇄창이 뜸)
                    st.components.v1.html(print_html, height=600, scrolling=True)

                # --- 수정 및 삭제 기능 (발주접수 상태만) ---
                st.divider()
                st.subheader("🛠️ 발주 내역 수정/삭제 (발주접수 상태만 가능)")
                
                # 테이블에서 선택된 행이 있는지 확인
                if selection.selection.rows:
                    selected_idx = selection.selection.rows[0]
                    # 선택된 행의 데이터 가져오기 (df는 필터링된 상태일 수 있으므로 iloc 사용)
                    sel_row = df.iloc[selected_idx]
                    sel_id = sel_row['id']
                    
                    if sel_row['status'] != '발주접수':
                        st.warning(f"선택하신 건은 현재 '{sel_row['status']}' 상태이므로 수정/삭제할 수 없습니다.")
                    else:
                        
                        # 수정 폼을 위해 기초 데이터 다시 로드
                        weaving_types = get_common_codes("weaving_types", ["30수 연사", "무지", "기타"])
                        customer_list = get_partners("발주처")

                        with st.form("edit_order_form"):
                            st.write(f"선택된 발주건: **{sel_row['customer']} - {sel_row['name']}**")
                            
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
                            e_del_date = ec10.date_input("납품요청일", datetime.datetime.strptime(sel_row['delivery_req_date'], "%Y-%m-%d").date() if sel_row.get('delivery_req_date') else datetime.date.today())
                            e_note = ec11.text_input("특이사항", value=sel_row.get('note', ''))
                            
                            ec12, ec13, ec14 = st.columns(3)
                            e_del_to = ec12.text_input("납품처", value=sel_row.get('delivery_to', ''))
                            e_del_contact = ec13.text_input("납품연락처", value=sel_row.get('delivery_contact', ''))
                            e_del_addr = ec14.text_input("납품주소", value=sel_row.get('delivery_address', ''))

                            c_btn1, c_btn2 = st.columns(2)
                            update_submitted = c_btn1.form_submit_button("수정 저장")
                            delete_submitted = c_btn2.form_submit_button("삭제 하기", type="primary")
                            
                            if update_submitted:
                                db.collection("inventory").document(sel_id).update({
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
                                
                            if delete_submitted:
                                db.collection("inventory").document(sel_id).delete()
                                st.success("삭제되었습니다.")
                                st.rerun()
                else:
                    st.info("👆 위 목록에서 수정할 행을 선택해주세요.")

            else:
                st.info("해당 기간에 조회된 데이터가 없습니다.")
        else:
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
                        if item.get('stock') > 0:
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

    # 탭 분리: 작업 대기/진행 vs 전체 조회
    tab1, tab2 = st.tabs(["🏭 작업 관리 (지시/완료)", "📋 제직 내역 조회"])

    with tab1:
        # '발주접수' 또는 '제직' 상태인 건만 가져오기
        # Firestore의 'in' 쿼리 사용
        # [수정] order_by("date") 제거 (복합 인덱스 오류 방지) -> 파이썬에서 정렬
        docs = db.collection("inventory").where("status", "in", ["발주접수", "제직"]).stream()
        
        rows = []
        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            rows.append(d)
            
        # 파이썬에서 날짜순 정렬
        rows.sort(key=lambda x: x['date'])
        
        if rows:
            for item in rows:
                with st.container():
                    # 카드 형태로 각 건 표시
                    c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 1, 2])
                    
                    # 상태에 따라 배지 색상 다르게 표시
                    status_color = "blue" if item['status'] == "제직" else "green"
                    c1.markdown(f"**[{item['status']}]** :{status_color}[{item.get('order_no', '-')}]")
                    c1.write(f"📅 {item['date'].strftime('%Y-%m-%d')}")
                    
                    c2.write(f"**{item['customer']}**")
                    c2.write(f"{item['name']}")
                    
                    c3.write(f"{item['weaving_type']} / {item['yarn_type']}")
                    c3.write(f"{item['color']} / {item['stock']}장")
                    
                    # 작업지시서 미리보기 (Expander)
                    with c4.expander("🖨️ 지시서"):
                        st.markdown(f"""
                        <div style="border:1px solid #000; padding:10px; font-size:12px;">
                            <h3 style="text-align:center; margin:0;">작 업 지 시 서</h3>
                            <hr>
                            <p><strong>발주번호:</strong> {item.get('order_no')}</p>
                            <p><strong>발 주 처:</strong> {item['customer']}</p>
                            <p><strong>제 품 명:</strong> {item['name']}</p>
                            <p><strong>제직타입:</strong> {item['weaving_type']}</p>
                            <p><strong>사    종:</strong> {item['yarn_type']}</p>
                            <p><strong>색상/수량:</strong> {item['color']} / {item['stock']}장</p>
                            <p><strong>중량/사이즈:</strong> {item['weight']}g / {item['size']}</p>
                            <p><strong>납품요청일:</strong> {item['delivery_req_date']}</p>
                            <p><strong>특이사항:</strong> {item.get('note', '-')}</p>
                        </div>
                        """, unsafe_allow_html=True)
                        st.caption("Ctrl+P로 인쇄")

                    # 상태 변경 버튼
                    if item['status'] == "발주접수":
                        if c5.button("제직 시작 ➡️", key=f"start_{item['id']}"):
                            db.collection("inventory").document(item['id']).update({"status": "제직"})
                            st.rerun()
                    elif item['status'] == "제직":
                        if c5.button("제직 완료 (염색으로) ➡️", key=f"end_{item['id']}"):
                            db.collection("inventory").document(item['id']).update({"status": "염색"})
                            st.rerun()
                    
                    st.divider()
        else:
            st.info("현재 제직 대기 중이거나 작업 중인 건이 없습니다.")

    with tab2:
        st.write("제직 공정에 있는 모든 내역을 조회합니다.")
        # 간단한 리스트 조회 구현 (필요 시 확장)
        st.caption("전체 제직 내역 조회 기능은 추후 업데이트 예정입니다.")

elif menu == "거래처관리":
    st.header("🏢 거래처 관리")
    
    tab1, tab2 = st.tabs(["➕ 거래처 등록", "📋 거래처 목록"])
    
    # 기초 코드에서 거래처 구분 가져오기
    partner_types = get_common_codes("partner_types", ["발주처", "염색업체", "봉제업체", "배송업체", "기타"])

    with tab1:
        with st.form("partner_form"):
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
