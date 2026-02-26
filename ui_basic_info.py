import streamlit as st
import pandas as pd
import datetime
import io
from firebase_admin import firestore
from utils import get_common_codes, manage_code_with_code, manage_code, search_address_api, get_partners

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
        # ... (거래처 등록 로직, ui_management.py와 동일) ...
        # 실제 구현 시에는 ui_management.py의 해당 부분을 그대로 복사해오면 됩니다.
        st.info("거래처 등록 기능은 ui_management.py의 코드를 그대로 사용합니다.")

    elif sub_menu == "거래처 목록":
        # ... (거래처 목록 로직, ui_management.py와 동일) ...
        st.info("거래처 목록 기능은 ui_management.py의 코드를 그대로 사용합니다.")

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