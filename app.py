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

# [수정] 상단 여백 축소 및 제목 스타일 변경
st.markdown("""
    <style>
        /* 메인 영역 상단 여백 줄이기 (기본값은 약 6rem) */
        .block-container {
            padding-top: 3rem !important;
        }
    </style>
""", unsafe_allow_html=True)

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
    st.markdown("<h2 style='text-align: center; margin-bottom: 20px;'>🏭 세안타올<br>생산관리 현황</h2>", unsafe_allow_html=True)
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

    with st.expander("⚙️ 기초정보관리", expanded=True):
        if st.button("📦 제품 관리", use_container_width=True):
            st.session_state["current_menu"] = "제품 관리"
            st.rerun()
        if st.button("🏢 거래처관리", use_container_width=True):
            st.session_state["current_menu"] = "거래처관리"
            st.rerun()
        if st.button("🏭 제직기관리", use_container_width=True):
            st.session_state["current_menu"] = "제직기관리"
            st.rerun()
        if st.button("📝 제품코드설정", use_container_width=True):
            st.session_state["current_menu"] = "제품코드설정"
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

# --- [NEW] 공통 함수: 기초 코드가 제품에 사용되었는지 확인 ---
@st.cache_data(ttl=60) # 1분 동안 결과 캐싱
def is_basic_code_used(code_key, name, code):
    """지정된 기초 코드가 'products' 컬렉션에서 사용되었는지 확인합니다."""
    query = None
    if code_key == "product_types":
        query = db.collection("products").where("product_type", "==", name).limit(1)
    elif code_key == "yarn_types_coded":
        query = db.collection("products").where("yarn_type", "==", name).limit(1)
    elif code_key == "size_codes":
        query = db.collection("products").where("size", "==", name).limit(1)
    elif code_key == "weight_codes":
        try:
            # 'weight' 필드는 숫자로 저장되어 있으므로 코드를 숫자로 변환하여 쿼리
            weight_val = int(code)
            query = db.collection("products").where("weight", "==", weight_val).limit(1)
        except (ValueError, TypeError):
            return False # 코드가 숫자가 아니면 사용될 수 없음
    
    return len(list(query.stream())) > 0 if query else False

# --- 공통 함수: 기초 코드 관리 UI ---

# 이름-코드 쌍 관리 함수
def manage_code_with_code(code_key, default_list, label):
    current_list = get_common_codes(code_key, default_list)

    st.markdown(f"##### 📋 현재 등록된 {label}")
    # 이전 버전 호환을 위해 딕셔너리 형태만 필터링
    current_list_dicts = [item for item in current_list if isinstance(item, dict)]
    if current_list_dicts:
        # 코드 기준 오름차순 정렬
        current_list_dicts.sort(key=lambda x: x.get('code', ''))
        df = pd.DataFrame(current_list_dicts, columns=['name', 'code'])
    else:
        df = pd.DataFrame(columns=['name', 'code'])

    selection = st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=f"df_{code_key}"
    )

    st.divider()

    # --- 수정 / 삭제 (항목 선택 시) ---
    if selection.selection.rows:
        idx = selection.selection.rows[0]
        sel_row = df.iloc[idx]
        sel_name = sel_row['name']
        sel_code = sel_row['code']

        is_used = is_basic_code_used(code_key, sel_name, sel_code)

        if is_used:
            st.subheader(f"ℹ️ '{sel_name}' 정보")
            st.warning("이 항목은 제품 등록에 사용되어 수정 및 삭제가 불가능합니다.")
            st.text_input("명칭", value=sel_name, disabled=True)
            st.text_input("코드", value=sel_code, disabled=True)
        else:
            # 수정 폼
            with st.form(key=f"edit_{code_key}"):
                st.subheader(f"🛠️ '{sel_name}' 수정")
                new_name = st.text_input("명칭", value=sel_name)
                new_code = st.text_input("코드", value=sel_code)

                if st.form_submit_button("수정 저장"):
                    if new_name and new_code:
                        # 새 명칭이 다른 항목에서 이미 사용 중인지 확인
                        is_name_taken = any(item.get('name') == new_name for item in current_list_dicts if item.get('name') != sel_name)
                        if is_name_taken:
                            st.error(f"'{new_name}'은(는) 이미 존재하는 명칭입니다.")
                        else:
                            for item in current_list_dicts:
                                if item.get('name') == sel_name: # 기존 이름으로 항목 찾기
                                    item['name'] = new_name # 이름 업데이트
                                    item['code'] = new_code # 코드 업데이트
                                    break
                            db.collection("settings").document("codes").set({code_key: current_list_dicts}, merge=True)
                            st.success("수정되었습니다.")
                            st.rerun()

            # 삭제 기능
            st.subheader(f"🗑️ '{sel_name}' 삭제")
            if st.button("이 항목 삭제하기", type="primary", key=f"del_btn_{code_key}"):
                updated_list = [item for item in current_list_dicts if item['name'] != sel_name]
                db.collection("settings").document("codes").set({code_key: updated_list}, merge=True)
                st.success("삭제되었습니다.")
                st.rerun()

    # --- 추가 (항목 미선택 시) ---
    else:
        st.subheader(f"➕ 신규 {label} 추가")
        if not df.empty:
            st.info("목록에서 항목을 선택하면 수정 또는 삭제할 수 있습니다.")

        with st.form(key=f"add_{code_key}", clear_on_submit=True):
            c1, c2 = st.columns(2)
            new_name = c1.text_input("명칭")
            new_code = c2.text_input("코드")
            if st.form_submit_button("추가"):
                if new_name and new_code:
                    if any(item.get('name') == new_name for item in current_list_dicts):
                        st.error("이미 존재하는 명칭입니다.")
                    else:
                        current_list_dicts.append({'name': new_name, 'code': new_code})
                        db.collection("settings").document("codes").set({code_key: current_list_dicts}, merge=True)
                        st.success("추가되었습니다.")
                        st.rerun()
                else:
                    st.warning("명칭과 코드를 모두 입력해주세요.")

# 단순 리스트 관리 함수
def manage_code(code_key, default_list, label):
    current_list = get_common_codes(code_key, default_list)
    st.markdown(f"##### 📋 현재 등록된 {label}")
    if current_list: st.dataframe(pd.DataFrame(current_list, columns=["명칭"]), use_container_width=True, hide_index=True)
    else: st.info("등록된 항목이 없습니다.")
    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        new_val = st.text_input(f"추가할 {label} 입력", key=f"new_{code_key}")
        if st.button(f"추가", key=f"btn_add_{code_key}"):
            if new_val and new_val not in current_list:
                current_list.append(new_val)
                db.collection("settings").document("codes").set({code_key: current_list}, merge=True)
                st.success("추가되었습니다."); st.rerun()
    with c2:
        del_val = st.selectbox(f"삭제할 {label} 선택", ["선택하세요"] + current_list, key=f"del_{code_key}")
        if st.button(f"삭제", key=f"btn_del_{code_key}"):
            if del_val != "선택하세요":
                current_list.remove(del_val)
                db.collection("settings").document("codes").set({code_key: current_list}, merge=True)
                st.success("삭제되었습니다."); st.rerun()

# 4. [메인 화면] 메뉴별 기능 구현
if menu == "발주서접수":
    st.header("📑 발주서 접수")
    st.info("신규 발주서를 등록합니다. 개별 등록 또는 엑셀 일괄 업로드가 가능합니다.")
    
    # [NEW] 데이터프레임 리셋을 위한 동적 키 초기화
    if "order_df_key" not in st.session_state:
        st.session_state["order_df_key"] = 0

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

    if st.session_state["role"] == "admin":
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

        tab1, tab2 = st.tabs(["📝 개별 접수", "🗑️ 발주내역삭제(엑셀업로드)"])

        with tab1:
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
            with st.expander("🔍 제품 검색 필터", expanded=True):
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
                s_weight = f3.selectbox("중량", get_options("weight"), key="filter_wt")
                s_size = f4.selectbox("사이즈", get_options("size"), key="filter_sz")

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
                use_container_width=True,
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

        with tab2:
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
            
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_template.to_excel(writer, index=False)
                
            st.download_button(
                label="📥 업로드용 양식 다운로드",
                data=buffer.getvalue(),
                file_name="발주업로드양식.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            
            st.divider()
            st.subheader("🗑️ 발주 내역 삭제 (다중 선택)")
            st.info("삭제할 항목의 체크박스를 선택한 후 하단의 삭제 버튼을 누르세요.")
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
                    use_container_width=True,
                    on_select="rerun",
                    selection_mode="multi-row",
                    key="del_orders_selection"
                )
                
                # 선택된 행 삭제 처리
                if selection.selection.rows:
                    selected_indices = selection.selection.rows
                    selected_rows = df_del.iloc[selected_indices]
                    
                    if st.button(f"🗑️ 선택한 {len(selected_rows)}건 영구 삭제", type="primary"):
                        for idx, row in selected_rows.iterrows():
                            db.collection("orders").document(row['id']).delete()
                        st.success(f"{len(selected_rows)}건이 삭제되었습니다.")
                        st.rerun()
            else:
                st.info("삭제할 발주 내역이 없습니다.")
            
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
    else:
        st.info("관리자만 발주를 등록할 수 있습니다.")

elif menu == "발주현황":
    st.header("📊 발주 현황")
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
        status_options = ["발주접수", "제직대기", "제직중", "제직완료", "염색출고", "염색중", "염색완료", "봉제중", "봉제완료", "출고완료"]
        
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
                use_container_width=True, 
                hide_index=True,  # 맨 왼쪽 순번(0,1,2..) 숨기기
                on_select="rerun", # 선택 시 리런
                selection_mode="multi-row", # 다중 선택 가능으로 변경
                height=700 # [수정] 목록 높이 확대 (약 20행)
            )
            
            # [MOVED] 작업 영역 로직 (테이블 상단)
            if selection.selection.rows:
                selected_indices = selection.selection.rows
                selected_rows = df.iloc[selected_indices]
                
                with action_placeholder:
                    # 1. 일괄 상태 변경 (Expander로 구성)
                    with st.expander("🚀 상태 일괄 변경 (제직대기 발송 등)", expanded=True):
                        c_batch1, c_batch2 = st.columns([3, 1])
                        with c_batch1:
                            target_status = st.selectbox("선택한 항목의 상태를 변경합니다:", ["제직대기", "발주접수"], key="batch_status_opt_top")
                        with c_batch2:
                            if st.button("상태 변경 적용", type="primary", key="btn_batch_update_top"):
                                count = 0
                                for idx, row in selected_rows.iterrows():
                                    db.collection("orders").document(row['id']).update({"status": target_status})
                                    count += 1
                                st.success(f"선택한 {count}건의 상태가 '{target_status}'(으)로 변경되었습니다.")
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
                                    🛠️ 선택한 내역 상세 수정 (화면 아래로 이동)
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
                
                st.divider()
                st.markdown("###### 📊 컬럼 설정 (순서 변경 및 너비 지정)")
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
                    use_container_width=True,
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
            if btn_c2.button("🖨️ 인쇄 페이지 열기"):
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
                            {custom_css}
                        </style>
                    </head>
                    <body>
                        <h2>{p_title}</h2>
                        <div class="info">출력일시: {print_date}</div>
                        <div class="no-print" style="text-align:right; margin-bottom:10px;">
                            <button onclick="window.print()" style="padding:8px 15px; font-size:14px; cursor:pointer; background-color:#4CAF50; color:white; border:none; border-radius:4px;">🖨️ 인쇄하기</button>
                        </div>
                        {print_df.to_html(index=False, border=1)}
                    </body>
                    </html>
                """
                # 인쇄용 HTML을 화면 하단에 렌더링 (스크립트로 인해 인쇄창이 뜸)
                st.components.v1.html(print_html, height=600, scrolling=True)

            # --- 상세 수정 (단일 선택 시에만) ---
            if len(selection.selection.rows) == 1:
                # 스크롤 이동을 위한 앵커
                st.markdown('<div id="edit_detail_section"></div>', unsafe_allow_html=True)
                st.divider()
                
                selected_idx = selection.selection.rows[0]
                # 선택된 행의 데이터 가져오기 (df는 필터링된 상태일 수 있으므로 iloc 사용)
                sel_row = df.iloc[selected_idx]
                sel_id = sel_row['id']
                
                # 수정 폼을 위해 기초 데이터 다시 로드
                product_types_coded = get_common_codes("product_types", [])
                product_type_names = [item['name'] for item in product_types_coded]
                customer_list = get_partners("발주처")

                st.subheader("🛠️ 발주 내역 상세 수정")
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
    running_docs = db.collection("orders").where("status", "==", "제직중").stream()
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
                        st.error(f"**{m_name}**\n\n{item.get('name')}\n({cur_roll}/{roll_cnt}롤) / {int(item.get('stock', 0)):,}장")
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
        # '제직대기' 상태인 건만 가져오기 (발주현황에서 '제직대기'로 변경된 건)
        docs = db.collection("orders").where("status", "==", "제직대기").stream()
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
            
            if 'delivery_req_date' in df.columns:
                df['delivery_req_date'] = pd.to_datetime(df['delivery_req_date'], errors='coerce').dt.strftime('%Y-%m-%d').fillna('')
            
            col_map = {
                "order_no": "발주번호", "status": "상태", "customer": "발주처", "name": "제품명", 
                "product_type": "제품종류", "weaving_type": "제품종류(구)", "yarn_type": "사종", "color": "색상", 
                "stock": "수량", "weight": "중량", "size": "사이즈", "date": "접수일", "delivery_req_date": "납품요청일"
            }
            display_cols = ["order_no", "status", "customer", "name", "stock", "product_type", "weaving_type", "yarn_type", "color", "weight", "size", "date", "delivery_req_date"]
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
                    # [수정] 제직기 명칭만 표시하도록 변경
                    m_display_map = {} # "표시명": "호기번호" 매핑
                    m_options = []
                    for m in machines_data:
                        m_no = str(m['machine_no'])
                        m_name = m['name']
                        if m_no in busy_machines:
                            display_str = f"{m_name} (사용중)"
                        else:
                            display_str = m_name
                        m_options.append(display_str)
                        m_display_map[display_str] = m_no
                    
                    s_machine = c1.selectbox("제직기 선택", m_options)
                    s_date = c2.date_input("시작일자", datetime.date.today(), format="YYYY-MM-DD")
                    s_time = c3.time_input("시작시간", datetime.datetime.now().time())
                    s_roll = c4.number_input("제직롤수량", min_value=1, step=1)
                    
                    if st.form_submit_button("제직 시작"):
                        sel_m_no = m_display_map.get(s_machine)
                        if sel_m_no in busy_machines:
                            st.error(f"⛔ 해당 제직기는 이미 작업 중입니다!")
                        else:
                            start_dt = datetime.datetime.combine(s_date, s_time)
                            db.collection("orders").document(sel_id).update({
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
            
        docs = db.collection("orders").where("status", "==", "제직중").stream()
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
                        parent_doc = db.collection("orders").document(sel_id).get().to_dict()
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
                        
                        db.collection("orders").add(new_roll_doc)
                        
                        # 2. 부모 문서 업데이트 (진행률 표시)
                        updates = {"completed_rolls": next_roll_no}
                        
                        # 마지막 롤이면 부모 문서는 '제직완료(Master)' 상태로 변경하여 목록에서 숨김
                        if next_roll_no >= total_rolls:
                            updates["status"] = "제직완료(Master)"
                            msg = f"🎉 마지막 롤({next_roll_no}/{total_rolls})까지 처리가 완료되었습니다!"
                        else:
                            msg = f"✅ {next_roll_no}번 롤 처리가 완료되었습니다. 이어서 {next_roll_no + 1}번 롤을 입력해주세요."
                        
                        db.collection("orders").document(sel_id).update(updates)
                        
                        # 메시지를 세션에 저장하여 리런 후에도 보이게 함
                        st.session_state["weaving_msg"] = msg
                        st.rerun()
                
                if st.button("🚫 제직 취소 (대기로 되돌리기)", key="cancel_weaving"):
                    db.collection("orders").document(sel_id).update({
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

        # [수정] 다음 공정으로 넘어간 내역도 조회되도록 상태 조건 확대
        # 제직완료 이후의 모든 상태 포함
        target_statuses = ["제직완료", "제직완료(Master)", "염색중", "염색완료", "봉제중", "봉제완료", "출고완료"]
        docs = db.collection("orders").where("status", "in", target_statuses).stream()
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
                        db.collection("orders").document(sel_id).update({
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
                    db.collection("orders").document(sel_id).delete()
                    
                    # 2. 부모 문서(제직중인 건) 상태 업데이트
                    if parent_id:
                        # 남은 형제 롤 개수 확인
                        siblings = db.collection("orders").where("parent_id", "==", parent_id).where("status", "==", "제직완료").stream()
                        cnt = sum(1 for _ in siblings)
                        
                        db.collection("orders").document(parent_id).update({
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
        
        # [수정] 데이터가 있는 날짜 목록 가져오기
        available_dates = set()
        # 1. 작업일지 데이터 날짜
        logs_ref = db.collection("shift_logs").stream()
        for doc in logs_ref:
            if doc.to_dict().get('log_date'):
                available_dates.add(doc.to_dict().get('log_date'))
        # 2. 전달사항 데이터 날짜 (문서 ID가 날짜)
        notes_ref = db.collection("handover_notes").stream()
        for doc in notes_ref:
            available_dates.add(doc.id)
            
        sorted_dates = sorted(list(available_dates), reverse=True)
        
        c1, c2 = st.columns([1, 3])
        view_date = c1.selectbox("조회할 날짜 선택", sorted_dates if sorted_dates else [str(datetime.date.today())], key="worklog_view_date")
        
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
        
        # [수정] 생산 실적이 있는 날짜 목록 가져오기
        # 제직완료 이상 상태인 건들의 weaving_end_time 확인
        target_statuses = ["제직완료", "제직완료(Master)", "염색중", "염색완료", "봉제중", "봉제완료", "출고완료"]
        inv_ref = db.collection("orders").where("status", "in", target_statuses).stream()
        prod_dates = set()
        for doc in inv_ref:
            d = doc.to_dict()
            w_end = d.get('weaving_end_time')
            if w_end:
                if isinstance(w_end, datetime.datetime):
                    prod_dates.add(w_end.strftime("%Y-%m-%d"))
                elif isinstance(w_end, str):
                    prod_dates.add(w_end[:10])
        
        sorted_prod_dates = sorted(list(prod_dates), reverse=True)
        
        c1, c2 = st.columns([1, 3])
        prod_date_str = c1.selectbox("조회일자 선택", sorted_prod_dates if sorted_prod_dates else [str(datetime.date.today())], key="prodlog_view_date")
        prod_date = datetime.datetime.strptime(prod_date_str, "%Y-%m-%d").date()
        
        start_dt = datetime.datetime.combine(prod_date, datetime.time.min)
        end_dt = datetime.datetime.combine(prod_date, datetime.time.max)
        
        # Firestore 인덱스 오류 방지를 위해 status만 쿼리하고 날짜는 파이썬에서 필터링
        docs = db.collection("orders").where("status", "in", target_statuses).stream()
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

    tab_dye_wait, tab_dye_ing, tab_dye_done = st.tabs(["📋 염색 대기 목록", "🏭 염색중 목록", "✅ 염색 완료 목록"])

    # 염색 업체 목록 가져오기
    dyeing_partners = get_partners("염색업체")

    # --- 1. 염색 대기 탭 ---
    with tab_dye_wait:
        st.subheader("염색 대기 목록 (제직완료)")
        docs = db.collection("orders").where("status", "==", "제직완료").stream()
        rows = []
        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            rows.append(d)
        
        # 날짜순 정렬
        rows.sort(key=lambda x: x.get('date', datetime.datetime.max))

        if rows:
            df = pd.DataFrame(rows)
            if 'date' in df.columns:
                df['date'] = df['date'].apply(lambda x: x.strftime('%Y-%m-%d') if not pd.isnull(x) and hasattr(x, 'strftime') else x)
            
            col_map = {
                "order_no": "발주번호", "customer": "발주처", "name": "제품명", 
                "color": "색상", "stock": "수량", "weight": "중량(g)", 
                "prod_weight_kg": "제직중량(kg)", "roll_no": "롤번호", "date": "접수일"
            }
            display_cols = ["order_no", "roll_no", "customer", "name", "color", "stock", "weight", "prod_weight_kg", "date"]
            final_cols = [c for c in display_cols if c in df.columns]
            
            st.write("🔽 염색 출고할 항목을 선택하세요.")
            selection = st.dataframe(df[final_cols].rename(columns=col_map), use_container_width=True, on_select="rerun", selection_mode="single-row", key="df_dye_wait")
            
            if selection.selection.rows:
                idx = selection.selection.rows[0]
                sel_row = df.iloc[idx]
                sel_id = sel_row['id']
                
                st.divider()
                st.markdown(f"### 🚚 염색 출고 정보 입력: **{sel_row['name']}**")
                
                with st.form("dyeing_start_form"):
                    c1, c2 = st.columns(2)
                    d_date = c1.date_input("염색출고일", datetime.date.today())
                    d_partner = c2.selectbox("염색업체", dyeing_partners if dyeing_partners else ["직접입력"])
                    
                    c3, c4 = st.columns(2)
                    # 기본값으로 제직 생산 중량 사용
                    def_weight = float(sel_row.get('prod_weight_kg', 0))
                    d_weight = c3.number_input("출고중량(kg)", value=def_weight, step=0.1, format="%.1f")
                    d_note = c4.text_input("염색사항(비고)")
                    
                    if st.form_submit_button("염색 출고 (작업시작)"):
                        db.collection("orders").document(sel_id).update({
                            "status": "염색중",
                            "dyeing_out_date": str(d_date),
                            "dyeing_partner": d_partner,
                            "dyeing_out_weight": d_weight,
                            "dyeing_note": d_note
                        })
                        st.success("염색중 상태로 변경되었습니다.")
                        st.rerun()
        else:
            st.info("염색 대기 중인 건이 없습니다.")

    # --- 2. 염색중 탭 ---
    with tab_dye_ing:
        st.subheader("염색중 목록")
        docs = db.collection("orders").where("status", "==", "염색중").stream()
        rows = []
        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            rows.append(d)
            
        if rows:
            df = pd.DataFrame(rows)
            col_map = {
                "order_no": "발주번호", "dyeing_partner": "염색업체", "dyeing_out_date": "출고일",
                "name": "제품명", "color": "색상", "stock": "수량", "dyeing_out_weight": "출고중량(kg)",
                "roll_no": "롤번호"
            }
            display_cols = ["dyeing_out_date", "dyeing_partner", "order_no", "roll_no", "name", "color", "stock", "dyeing_out_weight"]
            final_cols = [c for c in display_cols if c in df.columns]
            
            st.write("🔽 관리할 항목을 선택하세요.")
            selection = st.dataframe(df[final_cols].rename(columns=col_map), use_container_width=True, on_select="rerun", selection_mode="single-row", key="df_dye_ing")
            
            if selection.selection.rows:
                idx = selection.selection.rows[0]
                sel_row = df.iloc[idx]
                sel_id = sel_row['id']
                
                st.divider()
                st.markdown(f"### ⚙️ 작업 관리: **{sel_row['name']}**")
                
                tab_act1, tab_act2 = st.tabs(["✅ 염색 완료 처리", "🛠️ 정보 수정 / 취소"])
                
                with tab_act1:
                    st.write("염색 완료(입고) 정보를 입력하세요.")
                    c1, c2 = st.columns(2)
                    d_in_date = c1.date_input("염색완료일(입고일)", datetime.date.today())
                    d_stock = c2.number_input("입고수량(장)", value=int(sel_row.get('stock', 0)), step=10)
                    
                    c3, c4 = st.columns(2)
                    # 기본값으로 출고 중량 사용
                    def_weight = float(sel_row.get('dyeing_out_weight', 0)) if not pd.isna(sel_row.get('dyeing_out_weight')) else 0.0
                    d_weight = c3.number_input("입고중량(kg)", value=def_weight, step=0.1, format="%.1f")
                    d_price = c4.number_input("염색단가(원)", min_value=0, step=1)
                    
                    d_vat_inc = st.checkbox("부가세 포함", value=False, key="dye_vat_check")
                    
                    base_calc = int(d_weight * d_price)
                    if d_vat_inc:
                        d_supply = int(base_calc / 1.1)
                        d_vat = base_calc - d_supply
                        d_total = base_calc
                    else:
                        d_supply = base_calc
                        d_vat = int(base_calc * 0.1)
                        d_total = base_calc + d_vat
                    
                    st.info(f"💰 **염색비용 합계**: {d_total:,}원 (공급가: {d_supply:,}원 / 부가세: {d_vat:,}원)")
                    
                    if st.button("염색 완료 (봉제대기로 이동)"):
                        db.collection("orders").document(sel_id).update({
                            "status": "염색완료",
                            "dyeing_in_date": str(d_in_date),
                            "stock": d_stock,
                            "dyeing_in_weight": d_weight,
                            "dyeing_unit_price": d_price,
                            "dyeing_amount": d_total,
                            "dyeing_supply": d_supply,
                            "dyeing_vat": d_vat,
                            "vat_included": d_vat_inc
                        })
                        st.success(f"염색이 완료되었습니다. (합계: {d_total:,}원)")
                        st.rerun()
                            
                with tab_act2:
                    with st.form("dyeing_edit_form"):
                        st.write("출고 정보를 수정합니다.")
                        c1, c2 = st.columns(2)
                        e_date = c1.date_input("염색출고일", datetime.datetime.strptime(sel_row['dyeing_out_date'], "%Y-%m-%d").date() if sel_row.get('dyeing_out_date') else datetime.date.today())
                        e_partner = c2.selectbox("염색업체", dyeing_partners if dyeing_partners else ["직접입력"], index=dyeing_partners.index(sel_row['dyeing_partner']) if sel_row.get('dyeing_partner') in dyeing_partners else 0)
                        
                        c3, c4 = st.columns(2)
                        e_weight = c3.number_input("출고중량(kg)", value=float(sel_row.get('dyeing_out_weight', 0)), step=0.1, format="%.1f")
                        e_note = c4.text_input("염색사항", value=sel_row.get('dyeing_note', ''))
                        
                        if st.form_submit_button("수정 저장"):
                            db.collection("orders").document(sel_id).update({
                                "dyeing_out_date": str(e_date),
                                "dyeing_partner": e_partner,
                                "dyeing_out_weight": e_weight,
                                "dyeing_note": e_note
                            })
                            st.success("수정되었습니다.")
                            st.rerun()
                    
                    st.markdown("#### 🚫 작업 취소")
                    if st.button("염색 취소 (대기로 되돌리기)", type="primary"):
                        db.collection("orders").document(sel_id).update({
                            "status": "제직완료"
                        })
                        st.success("취소되었습니다.")
                        st.rerun()
        else:
            st.info("현재 염색 중인 작업이 없습니다.")

    # --- 3. 염색 완료 탭 ---
    with tab_dye_done:
        st.subheader("염색 완료 목록")
        
        # 검색 조건 (기간 + 염색업체)
        with st.form("search_dye_done"):
            c1, c2 = st.columns([2, 1])
            today = datetime.date.today()
            s_date = c1.date_input("조회 기간 (완료일)", [today - datetime.timedelta(days=30), today])
            s_partner = c2.text_input("염색업체 검색")
            st.form_submit_button("🔍 조회")

        # 날짜 범위 계산
        if len(s_date) == 2:
            start_dt = datetime.datetime.combine(s_date[0], datetime.time.min)
            end_dt = datetime.datetime.combine(s_date[1], datetime.time.max)
        else:
            start_dt = datetime.datetime.combine(s_date[0], datetime.time.min)
            end_dt = datetime.datetime.combine(s_date[0], datetime.time.max)

        # [수정] 다음 공정으로 넘어간 내역도 조회되도록 상태 조건 확대
        target_statuses = ["염색완료", "봉제중", "봉제완료", "출고완료"]
        docs = db.collection("orders").where("status", "in", target_statuses).stream()
        rows = []
        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            
            # 1. 날짜 필터 (dyeing_in_date 기준)
            d_date_str = d.get('dyeing_in_date')
            if d_date_str:
                try:
                    d_date_obj = datetime.datetime.strptime(d_date_str, "%Y-%m-%d")
                    if not (start_dt <= d_date_obj <= end_dt): continue
                except:
                    continue
            else:
                continue
            
            # 2. 염색업체 필터
            if s_partner and s_partner not in d.get('dyeing_partner', ''):
                continue
                
            rows.append(d)
            
        # 최신순 정렬 (완료일 기준)
        rows.sort(key=lambda x: x.get('dyeing_in_date', ''), reverse=True)

        if rows:
            df = pd.DataFrame(rows)
            
            # 금액 합계 표시
            total_amount = df['dyeing_amount'].sum() if 'dyeing_amount' in df.columns else 0
            st.markdown(f"### 💵 총 염색금액: **{total_amount:,}원** (총 {len(rows)}건)")
            
            col_map = {
                "order_no": "발주번호", "dyeing_partner": "염색업체", "dyeing_in_date": "완료일",
                "name": "제품명", "color": "색상", "stock": "수량", "roll_no": "롤번호",
                "dyeing_in_weight": "입고중량(kg)", "dyeing_unit_price": "단가", "dyeing_amount": "금액"
            }
            display_cols = ["dyeing_in_date", "dyeing_partner", "order_no", "roll_no", "name", "color", "stock", "dyeing_in_weight", "dyeing_unit_price", "dyeing_amount"]
            final_cols = [c for c in display_cols if c in df.columns]
            
            st.write("🔽 수정하거나 취소할 항목을 선택하세요.")
            selection = st.dataframe(df[final_cols].rename(columns=col_map), use_container_width=True, on_select="rerun", selection_mode="single-row", key="df_dye_done")
            
            if selection.selection.rows:
                idx = selection.selection.rows[0]
                sel_row = df.iloc[idx]
                sel_id = sel_row['id']
                
                st.divider()
                st.markdown(f"### 🛠️ 완료 정보 수정: **{sel_row['name']}**")
                
                c1, c2 = st.columns(2)
                with c1:
                    with st.form("dyeing_done_edit"):
                        st.write("입고 정보 수정")
                        new_in_date = st.date_input("염색완료일", datetime.datetime.strptime(sel_row['dyeing_in_date'], "%Y-%m-%d").date() if sel_row.get('dyeing_in_date') else datetime.date.today())
                        
                        c_e1, c_e2 = st.columns(2)
                        new_stock = c_e1.number_input("입고수량(장)", value=int(sel_row.get('stock', 0)), step=10)
                        new_weight = c_e2.number_input("입고중량(kg)", value=float(sel_row.get('dyeing_in_weight', 0)) if not pd.isna(sel_row.get('dyeing_in_weight')) else 0.0, step=0.1, format="%.1f")
                        
                        c_e3, c_e4 = st.columns(2)
                        new_price = c_e3.number_input("단가(원)", value=int(sel_row.get('dyeing_unit_price', 0)) if not pd.isna(sel_row.get('dyeing_unit_price')) else 0, step=1)
                        
                        if st.form_submit_button("수정 저장"):
                            new_amount = int(new_weight * new_price)
                            db.collection("orders").document(sel_id).update({
                                "dyeing_in_date": str(new_in_date),
                                "stock": new_stock,
                                "dyeing_in_weight": new_weight,
                                "dyeing_unit_price": new_price,
                                "dyeing_amount": new_amount
                            })
                            st.success("수정되었습니다.")
                            st.rerun()
                
                with c2:
                    st.write("🚫 **완료 취소**")
                    st.warning("상태를 다시 '염색중'으로 되돌립니다.")
                    if st.button("완료 취소 (염색중으로 복귀)", type="primary"):
                        db.collection("orders").document(sel_id).update({
                            "status": "염색중"
                        })
                        st.success("복귀되었습니다.")
                        st.rerun()
        else:
            st.info("염색 완료된 내역이 없습니다.")

elif menu == "봉제현황":
    st.header("🪡 봉제 현황")
    st.info("염색이 완료된 원단을 봉제하여 완제품으로 만듭니다.")
    
    tab_sew_wait, tab_sew_ing, tab_sew_done = st.tabs(["📋 봉제 대기 목록", "🪡 봉제중 목록", "✅ 봉제 완료 목록"])
    
    sewing_partners = get_partners("봉제업체")
    
    # --- 1. 봉제 대기 탭 ---
    with tab_sew_wait:
        st.subheader("봉제 대기 목록 (염색완료)")
        docs = db.collection("orders").where("status", "==", "염색완료").stream()
        rows = []
        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            rows.append(d)
        
        # 날짜순 정렬
        rows.sort(key=lambda x: x.get('date', datetime.datetime.max))
        
        if rows:
            df = pd.DataFrame(rows)
            if 'date' in df.columns:
                df['date'] = df['date'].apply(lambda x: x.strftime('%Y-%m-%d') if not pd.isnull(x) and hasattr(x, 'strftime') else x)
            
            col_map = {
                "order_no": "발주번호", "customer": "발주처", "name": "제품명", 
                "color": "색상", "stock": "수량(장)", "dyeing_partner": "염색처", "date": "접수일"
            }
            display_cols = ["order_no", "customer", "name", "color", "stock", "dyeing_partner", "date"]
            final_cols = [c for c in display_cols if c in df.columns]
            
            st.write("🔽 봉제 작업할 항목을 선택하세요.")
            selection = st.dataframe(df[final_cols].rename(columns=col_map), use_container_width=True, on_select="rerun", selection_mode="single-row", key="df_sew_wait")
            
            if selection.selection.rows:
                idx = selection.selection.rows[0]
                sel_row = df.iloc[idx]
                sel_id = sel_row['id']
                current_stock = int(sel_row.get('stock', 0))
                
                st.divider()
                st.markdown(f"### 🧵 봉제 작업 시작: **{sel_row['name']}**")
                
                # st.form 제거 (라디오 버튼 즉시 반응을 위해)
                c1, c2 = st.columns(2)
                s_date = c1.date_input("봉제시작일", datetime.date.today())
                s_type = c2.radio("작업 구분", ["자체봉제", "외주봉제"], horizontal=True, key=f"s_type_{sel_id}")
                
                c3, c4 = st.columns(2)
                s_partner = c3.selectbox("봉제업체", sewing_partners if sewing_partners else ["직접입력"], disabled=(s_type=="자체봉제"), key=f"s_partner_{sel_id}")
                s_qty = c4.number_input("작업 수량(장)", min_value=1, max_value=current_stock, value=current_stock, step=10, help="일부 수량만 작업하려면 숫자를 줄이세요.", key=f"s_qty_{sel_id}")
                
                if st.button("봉제 시작", key=f"btn_start_sew_{sel_id}"):
                    # 수량 분할 로직
                    if s_qty < current_stock:
                        # 1. 분할된 새 문서 생성 (작업분)
                        doc_snapshot = db.collection("orders").document(sel_id).get()
                        new_doc_data = doc_snapshot.to_dict().copy()
                        new_doc_data['stock'] = s_qty
                        new_doc_data['status'] = "봉제중"
                        new_doc_data['sewing_type'] = s_type
                        new_doc_data['sewing_start_date'] = str(s_date)
                        if s_type == "외주봉제":
                            new_doc_data['sewing_partner'] = s_partner
                        else:
                            new_doc_data['sewing_partner'] = "자체"
                        
                        db.collection("orders").add(new_doc_data)
                        
                        # 2. 원본 문서 업데이트 (잔여분)
                        db.collection("orders").document(sel_id).update({
                            "stock": current_stock - s_qty
                        })
                        st.success(f"{s_qty}장 분할하여 봉제 작업을 시작합니다. (잔여: {current_stock - s_qty}장)")
                    else:
                        # 전체 작업
                        updates = {
                            "status": "봉제중",
                            "sewing_type": s_type,
                            "sewing_start_date": str(s_date)
                        }
                        if s_type == "외주봉제":
                            updates['sewing_partner'] = s_partner
                        else:
                            updates['sewing_partner'] = "자체"
                            
                        db.collection("orders").document(sel_id).update(updates)
                        st.success("봉제 작업을 시작합니다.")
                    
                    st.rerun()
        else:
            st.info("봉제 대기 중인 건이 없습니다.")
            
    # --- 2. 봉제중 탭 ---
    with tab_sew_ing:
        st.subheader("봉제중 목록")
        docs = db.collection("orders").where("status", "==", "봉제중").stream()
        rows = []
        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            rows.append(d)
            
        if rows:
            df = pd.DataFrame(rows)
            col_map = {
                "order_no": "발주번호", "sewing_partner": "봉제처", "sewing_type": "구분",
                "name": "제품명", "color": "색상", "stock": "수량", "sewing_start_date": "시작일"
            }
            display_cols = ["sewing_start_date", "sewing_type", "sewing_partner", "order_no", "name", "color", "stock"]
            final_cols = [c for c in display_cols if c in df.columns]
            
            st.write("🔽 완료 처리할 항목을 선택하세요.")
            selection = st.dataframe(df[final_cols].rename(columns=col_map), use_container_width=True, on_select="rerun", selection_mode="single-row", key="df_sew_ing")
            
            if selection.selection.rows:
                idx = selection.selection.rows[0]
                sel_row = df.iloc[idx]
                sel_id = sel_row['id']
                
                st.divider()
                st.markdown(f"### ✅ 봉제 완료 처리: **{sel_row['name']}**")
                
                tab_act1, tab_act2 = st.tabs(["✅ 봉제 완료 처리", "🛠️ 정보 수정 / 취소"])
                
                with tab_act1:
                    st.write("봉제 완료 정보를 입력하세요.")
                    c1, c2 = st.columns(2)
                    s_end_date = c1.date_input("봉제완료일", datetime.date.today())
                    s_real_stock = c2.number_input("완료수량(장)", value=int(sel_row.get('stock', 0)), step=10)
                    
                    # 외주봉제일 경우 단가/금액 입력
                    s_price = 0
                    s_total = 0
                    s_supply = 0
                    s_vat = 0
                    s_vat_inc = False
                    
                    if sel_row.get('sewing_type') == "외주봉제":
                        st.markdown("#### 💰 외주 가공비 정산")
                        c3, c4 = st.columns(2)
                        s_price = c3.number_input("봉제단가(원)", min_value=0, step=1)
                        s_vat_inc = c4.checkbox("부가세 포함", value=False, key="sew_vat_check")
                        
                        base_calc = int(s_real_stock * s_price)
                        if s_vat_inc:
                            s_supply = int(base_calc / 1.1)
                            s_vat = base_calc - s_supply
                            s_total = base_calc
                        else:
                            s_supply = base_calc
                            s_vat = int(base_calc * 0.1)
                            s_total = base_calc + s_vat
                            
                        st.info(f"**봉제비용 합계**: {s_total:,}원 (공급가: {s_supply:,}원 / 부가세: {s_vat:,}원)")
                    
                    if st.button("봉제 완료 (출고대기로 이동)"):
                        updates = {
                            "status": "봉제완료",
                            "sewing_end_date": str(s_end_date),
                            "stock": s_real_stock
                        }
                        if sel_row.get('sewing_type') == "외주봉제":
                            updates["sewing_unit_price"] = s_price
                            updates["sewing_amount"] = s_total
                            updates["sewing_supply"] = s_supply
                            updates["sewing_vat"] = s_vat
                            updates["vat_included"] = s_vat_inc
                        
                        db.collection("orders").document(sel_id).update(updates)
                        st.success("봉제 완료 처리되었습니다.")
                        st.rerun()
                            
                with tab_act2:
                    with st.form("sewing_edit_form"):
                        st.write("작업 정보 수정")
                        c1, c2 = st.columns(2)
                        e_date = c1.date_input("봉제시작일", datetime.datetime.strptime(sel_row['sewing_start_date'], "%Y-%m-%d").date() if sel_row.get('sewing_start_date') else datetime.date.today())
                        e_type = c2.radio("작업 구분", ["자체봉제", "외주봉제"], horizontal=True, index=0 if sel_row.get('sewing_type') == "자체봉제" else 1)
                        
                        e_partner = st.selectbox("봉제업체", sewing_partners if sewing_partners else ["직접입력"], index=sewing_partners.index(sel_row['sewing_partner']) if sel_row.get('sewing_partner') in sewing_partners else 0)
                        
                        if st.form_submit_button("수정 저장"):
                            updates = {
                                "sewing_start_date": str(e_date),
                                "sewing_type": e_type,
                                "sewing_partner": "자체" if e_type == "자체봉제" else e_partner
                            }
                            db.collection("orders").document(sel_id).update(updates)
                            st.success("수정되었습니다.")
                            st.rerun()
                    
                    st.markdown("#### 🚫 작업 취소")
                    if st.button("봉제 취소 (대기로 되돌리기)", type="primary"):
                        db.collection("orders").document(sel_id).update({
                            "status": "염색완료"
                        })
                        st.success("취소되었습니다.")
                        st.rerun()
        else:
            st.info("현재 봉제 중인 작업이 없습니다.")

    # --- 3. 봉제 완료 탭 ---
    with tab_sew_done:
        st.subheader("봉제 완료 목록")
        
        # 검색 및 엑셀 다운로드
        with st.form("search_sew_done"):
            c1, c2 = st.columns([2, 1])
            today = datetime.date.today()
            s_date = c1.date_input("조회 기간 (완료일)", [today - datetime.timedelta(days=30), today])
            s_partner = c2.text_input("봉제업체 검색")
            st.form_submit_button("🔍 조회")
            
        # 날짜 범위 계산
        if len(s_date) == 2:
            start_dt = datetime.datetime.combine(s_date[0], datetime.time.min)
            end_dt = datetime.datetime.combine(s_date[1], datetime.time.max)
        else:
            start_dt = datetime.datetime.combine(s_date[0], datetime.time.min)
            end_dt = datetime.datetime.combine(s_date[0], datetime.time.max)
            
        # [수정] 다음 공정으로 넘어간 내역도 조회되도록 상태 조건 확대
        target_statuses = ["봉제완료", "출고완료"]
        docs = db.collection("orders").where("status", "in", target_statuses).stream()
        rows = []
        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            
            # 날짜 필터
            s_end = d.get('sewing_end_date')
            if s_end:
                try:
                    s_end_obj = datetime.datetime.strptime(s_end, "%Y-%m-%d")
                    if not (start_dt <= s_end_obj <= end_dt): continue
                except: continue
            else: continue
            
            # 업체 필터
            if s_partner and s_partner not in d.get('sewing_partner', ''):
                continue
                
            rows.append(d)
            
        rows.sort(key=lambda x: x.get('sewing_end_date', ''), reverse=True)
        
        if rows:
            df = pd.DataFrame(rows)
            
            # 금액 합계 (외주봉제만)
            total_amount = df['sewing_amount'].sum() if 'sewing_amount' in df.columns else 0
            st.markdown(f"### 💵 외주봉제 총 금액: **{total_amount:,}원**")
            
            col_map = {
                "order_no": "발주번호", "sewing_partner": "봉제처", "sewing_end_date": "완료일",
                "name": "제품명", "color": "색상", "stock": "수량", "sewing_type": "구분",
                "sewing_unit_price": "단가", "sewing_amount": "금액"
            }
            display_cols = ["sewing_end_date", "sewing_type", "sewing_partner", "order_no", "name", "color", "stock", "sewing_unit_price", "sewing_amount"]
            final_cols = [c for c in display_cols if c in df.columns]
            
            df_display = df[final_cols].rename(columns=col_map)
            
            st.write("🔽 수정하거나 취소할 항목을 선택하세요.")
            selection = st.dataframe(df_display, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row", key="df_sew_done")
            
            # 엑셀 다운로드
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_display.to_excel(writer, index=False)
                
            c_dl1, c_dl2 = st.columns([1, 5])
            c_dl1.download_button(
                label="💾 엑셀 다운로드",
                data=buffer.getvalue(),
                file_name=f"봉제완료내역_{today}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            
            if selection.selection.rows:
                idx = selection.selection.rows[0]
                sel_row = df.iloc[idx]
                sel_id = sel_row['id']
                
                st.divider()
                st.markdown(f"### 🛠️ 완료 정보 수정: **{sel_row['name']}**")
                
                c1, c2 = st.columns(2)
                with c1:
                    with st.form("sewing_done_edit"):
                        st.write("완료 정보 수정")
                        new_end_date = st.date_input("봉제완료일", datetime.datetime.strptime(sel_row['sewing_end_date'], "%Y-%m-%d").date() if sel_row.get('sewing_end_date') else datetime.date.today())
                        new_stock = st.number_input("완료수량(장)", value=int(sel_row.get('stock', 0)), step=10)
                        
                        new_price = 0
                        if sel_row.get('sewing_type') == "외주봉제":
                            new_price = st.number_input("봉제단가(원)", value=int(sel_row.get('sewing_unit_price', 0)) if not pd.isna(sel_row.get('sewing_unit_price')) else 0, step=1)
                        
                        if st.form_submit_button("수정 저장"):
                            updates = {
                                "sewing_end_date": str(new_end_date),
                                "stock": new_stock
                            }
                            if sel_row.get('sewing_type') == "외주봉제":
                                updates["sewing_unit_price"] = new_price
                                updates["sewing_amount"] = int(new_stock * new_price)
                                
                            db.collection("orders").document(sel_id).update(updates)
                            st.success("수정되었습니다.")
                            st.rerun()
                with c2:
                    st.write("🚫 **완료 취소**")
                    if st.button("완료 취소 (봉제중으로 복귀)", type="primary"):
                        db.collection("orders").document(sel_id).update({"status": "봉제중"})
                        st.success("복귀되었습니다.")
                        st.rerun()
        else:
            st.info("조회된 봉제 완료 내역이 없습니다.")

elif menu == "출고현황":
    st.header("🚚 출고 현황")
    st.info("완성된 제품을 출고 처리하거나, 출고된 내역의 거래명세서를 발행합니다.")
    
    tab1, tab2 = st.tabs(["🚀 출고 대기 관리", "📋 출고 완료 내역 (명세서)"])
    
    with tab1:
        # '봉제완료' (출고대기) 상태
        docs = db.collection("orders").where("status", "==", "봉제완료").stream()
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
                            db.collection("orders").document(item['id']).update({
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
        docs = db.collection("orders").where("status", "==", "출고완료").stream()
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
                                    <td style="border:1px solid #333; padding:10px;">{item.get('product_type', item.get('weaving_type', ''))}</td>
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

elif menu == "제품 관리":
    st.header("📦 제품 마스터 관리")
    st.info("제품의 고유한 특성(제품종류, 사종, 중량, 사이즈)을 조합하여 제품 코드를 생성하고 관리합니다.")

    # 제품종류, 사종 기초 코드 가져오기
    # 기초코드설정 메뉴와 동일한 기본값 사용
    default_product_types = [{'name': '세면타올', 'code': 'A'}, {'name': '바스타올', 'code': 'B'}, {'name': '핸드타올', 'code': 'H'}, {'name': '발매트', 'code': 'M'}, {'name': '스포츠타올', 'code': 'S'}]
    default_yarn_types = [{'name': '20수', 'code': '20S'}, {'name': '30수', 'code': '30S'}]
    product_types_coded = get_common_codes("product_types", default_product_types)
    yarn_types_coded = get_common_codes("yarn_types_coded", default_yarn_types)
    weight_codes = get_common_codes("weight_codes", [])
    size_codes = get_common_codes("size_codes", [])

    # 탭 순서 변경: 목록이 먼저 나오도록 수정
    tab1, tab2 = st.tabs(["📋 제품 목록", "➕ 제품 등록"])

    with tab1:
        st.subheader("등록된 제품 목록")
        # created_at 필드가 없는 과거 데이터(P0001 등)도 모두 조회하기 위해 정렬 조건 제거
        product_docs = list(db.collection("products").stream())
        if product_docs:
            products_data = [doc.to_dict() for doc in product_docs]
            df_products = pd.DataFrame(products_data)
            
            col_map = {
                "product_code": "제품코드", "product_type": "제품종류", "yarn_type": "사종",
                "weight": "중량(g)", "size": "사이즈", "created_at": "등록일"
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

            display_cols = ["product_code", "product_type", "yarn_type", "weight", "size", "created_at"]
            final_cols = [c for c in display_cols if c in df_products.columns] # 실제 존재하는 컬럼만 선택
            df_display = df_products[final_cols].rename(columns=col_map)
            
            st.write("🔽 삭제할 제품을 선택(체크)하세요. (다중 선택 가능)")
            selection = st.dataframe(
                df_display, 
                use_container_width=True, 
                hide_index=True,
                on_select="rerun",
                selection_mode="multi-row",
                key="product_list_selection"
            )
            
            # 삭제 기능
            if selection.selection.rows:
                st.divider()
                st.subheader("🗑️ 제품 삭제")
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

    with tab2:
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
                    "created_at": datetime.datetime.now()
                }
                db.collection("products").document(product_code).set(product_data)
                st.session_state["product_reg_msg"] = f"✅ 신규 제품코드 [{product_code}]가 성공적으로 등록되었습니다."
                # 콤보박스 초기화를 위해 리셋 플래그 설정
                st.session_state["trigger_reset"] = True
                st.rerun()

elif menu == "거래처관리":
    st.header("🏢 거래처 관리")
    
    tab1, tab2, tab3 = st.tabs(["➕ 거래처 등록", "📋 거래처 목록", "⚙️ 거래처 구분 관리"])
    
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
            
            # 화면 표시용 (id 제외)
            df_display = df[all_cols].rename(columns=col_map)
            
            st.write("🔽 수정할 거래처를 선택하세요.")
            selection = st.dataframe(df_display, use_container_width=True, on_select="rerun", selection_mode="single-row", key="partner_list")
            
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
                st.subheader(f"🛠️ 거래처 수정: {sel_row['name']}")
                
                with st.form("edit_partner_form"):
                    c1, c2 = st.columns(2)
                    e_type = c1.selectbox("거래처 구분", partner_types, index=partner_types.index(sel_row['type']) if sel_row['type'] in partner_types else 0)
                    e_name = c2.text_input("거래처명", value=sel_row['name'])
                    
                    c1, c2, c3 = st.columns(3)
                    e_rep = c1.text_input("대표자명", value=sel_row['rep_name'])
                    e_biz = c2.text_input("사업자번호", value=sel_row['biz_num'])
                    e_item = c3.text_input("업태/종목", value=sel_row['item'])
                    
                    c1, c2, c3 = st.columns(3)
                    e_phone = c1.text_input("전화번호", value=sel_row['phone'])
                    e_fax = c2.text_input("팩스번호", value=sel_row['fax'])
                    e_email = c3.text_input("이메일", value=sel_row['email'])
                    
                    e_addr = st.text_input("주소", value=sel_row['address'])
                    e_acc = st.text_input("계좌번호", value=sel_row['account'])
                    e_note = st.text_area("기타사항", value=sel_row['note'])
                    
                    if st.form_submit_button("수정 저장"):
                        db.collection("partners").document(sel_id).update({
                            "type": e_type,
                            "name": e_name,
                            "rep_name": e_rep,
                            "biz_num": e_biz,
                            "item": e_item,
                            "phone": e_phone,
                            "fax": e_fax,
                            "email": e_email,
                            "address": e_addr,
                            "account": e_acc,
                            "note": e_note
                        })
                        st.success("수정되었습니다.")
                        st.rerun()
            
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

    with tab3:
        st.subheader("거래처 구분 관리")
        st.info("거래처 등록 시 사용할 구분을 관리합니다.")
        manage_code("partner_types", partner_types, "거래처 구분")

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
            
            # 화면 표시용
            df_display = df[["machine_no", "name", "model", "note"]].rename(columns=col_map)
            
            st.write("🔽 수정할 제직기를 선택하세요.")
            selection = st.dataframe(df_display, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row", key="machine_list")
            
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
                st.subheader(f"🛠️ 제직기 수정: {sel_item['name']}")
                
                with st.form("edit_machine_form"):
                    c1, c2 = st.columns(2)
                    e_no = c1.number_input("호기 번호", value=int(sel_item['machine_no']), step=1, disabled=True)
                    e_name = c2.text_input("명칭", value=sel_item['name'])
                    c3, c4 = st.columns(2)
                    e_model = c3.text_input("모델명", value=sel_item.get('model', ''))
                    e_note = c4.text_input("비고", value=sel_item.get('note', ''))
                    
                    if st.form_submit_button("수정 저장"):
                        db.collection("machines").document(sel_id).update({"name": e_name, "model": e_model, "note": e_note})
                        st.success("수정되었습니다.")
                        st.rerun()
                
                if st.button("🗑️ 이 제직기 삭제", type="primary"):
                    db.collection("machines").document(sel_id).delete()
                    st.success("삭제되었습니다.")
                    st.rerun()
elif menu == "제품코드설정":
    st.header("📝 제품코드 설정")
    st.info("제품 코드 생성을 위한 각 부분의 코드 및 포맷을 설정합니다.")

    tab1, tab2, tab3, tab4 = st.tabs(["제품 종류", "사종", "중량", "사이즈"])

    with tab1:
        manage_code_with_code("product_types", [{'name': '세면타올', 'code': 'A'}, {'name': '바스타올', 'code': 'B'}, {'name': '핸드타올', 'code': 'H'}, {'name': '발매트', 'code': 'M'}, {'name': '스포츠타올', 'code': 'S'}], "제품 종류")
    
    with tab2:
        manage_code_with_code("yarn_types_coded", [{'name': '20수', 'code': '20S'}, {'name': '30수', 'code': '30S'}], "사종")

    with tab3:
        manage_code_with_code("weight_codes", [], "중량")

    with tab4:
        manage_code_with_code("size_codes", [], "사이즈")

else:
    st.header(f"🏗️ {menu}")
    st.info(f"'{menu}' 기능은 추후 업데이트될 예정입니다.")
