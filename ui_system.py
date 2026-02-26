import streamlit as st
import pandas as pd
import datetime
import base64
from firebase_admin import firestore
from utils import get_partners, validate_password, search_address_api

def render_users(db, sub_menu):
    st.header("사용자 관리")

    # [NEW] 전체 권한 목록 (사이드바 메뉴 기준)
    all_permissions = [
        "공지사항", "업무일정", "발주서접수", "발주현황", "제직현황", "제직조회",
        "염색현황", "봉제현황", "출고작업", "출고현황", "재고현황",
        "제품 관리", "거래처관리", "제직기관리", "제품코드설정",
        # 파트너용 메뉴
        "발주현황(거래처)", "재고현황(거래처)"
    ]
    
    if sub_menu == "사용자 등록":
        st.subheader("신규 사용자 등록")
        
        partners = get_partners() # For linking partner accounts

        with st.form("add_user_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            user_id = c1.text_input("아이디", help="로그인 시 사용할 고유 아이디입니다.")
            name = c2.text_input("이름")
            
            c3, c4 = st.columns(2)
            password = c3.text_input("초기 비밀번호", type="password", value="0000", help="최초 로그인 시 변경해야 합니다.")
            phone = c4.text_input("연락처")
            
            c5, c6 = st.columns(2)
            role = c5.selectbox("권한", ["admin", "user", "partner"], help="admin: 모든 권한, user: 직원, partner: 거래처")
            department = c6.text_input("부서/직책")
            
            linked_partner = ""
            if role == "partner":
                linked_partner = st.selectbox("연동 거래처", ["선택하세요"] + partners, help="이 계정과 연결할 거래처를 선택하세요.")

            permissions = st.multiselect("메뉴 접근 권한", all_permissions, help="이 사용자에게 허용할 메뉴를 선택하세요. (admin은 모든 메뉴에 접근 가능)")

            if st.form_submit_button("등록"):
                if user_id and name and password:
                    doc_ref = db.collection("users").document(user_id)
                    if doc_ref.get().exists:
                        st.error(f"이미 존재하는 아이디입니다: {user_id}")
                    else:
                        user_data = {
                            "username": user_id,
                            "name": name,
                            "password": password,
                            "phone": phone,
                            "role": role,
                            "department": department,
                            "permissions": permissions,
                            "linked_partner": linked_partner if role == "partner" and linked_partner != "선택하세요" else "",
                            "created_at": datetime.datetime.now()
                        }
                        doc_ref.set(user_data)
                        st.success(f"사용자 '{name}'({user_id})가 등록되었습니다.")
                else:
                    st.warning("아이디, 이름, 비밀번호는 필수 항목입니다.")

    elif sub_menu == "사용자 목록":
        st.subheader("사용자 목록")
        users_ref = db.collection("users").stream()
        user_list = []
        for doc in users_ref:
            item = doc.to_dict()
            item['id'] = doc.id
            user_list.append(item)
        
        if not user_list:
            st.warning("등록된 사용자가 없습니다.")
        else:
            df = pd.DataFrame(user_list)
            col_map = {"username": "아이디", "name": "이름", "role": "권한", "department": "부서/직책", "phone": "연락처", "linked_partner": "연동거래처"}
            
            display_cols = ["username", "name", "role", "department", "phone", "linked_partner"]
            final_cols = [c for c in display_cols if c in df.columns]
            
            df_display = df[final_cols].rename(columns=col_map)
            
            st.write("🔽 수정할 사용자를 선택하세요.")
            selection = st.dataframe(df_display, width="stretch", hide_index=True, on_select="rerun", selection_mode="single-row", key="user_list")
            
            if selection.selection.rows:
                idx = selection.selection.rows[0]
                sel_item = user_list[idx]
                sel_id = sel_item['id']
                
                st.divider()
                st.subheader(f"사용자 정보 수정: {sel_item['name']}")
                
                with st.form(f"edit_user_form_{sel_id}"):
                    c1, c2 = st.columns(2)
                    e_name = c1.text_input("이름", value=sel_item.get('name', ''))
                    e_phone = c2.text_input("연락처", value=sel_item.get('phone', ''))
                    
                    c3, c4 = st.columns(2)
                    role_opts = ["admin", "user", "partner"]
                    e_role = c3.selectbox("권한", role_opts, index=role_opts.index(sel_item['role']) if sel_item.get('role') in role_opts else 0)
                    e_dept = c4.text_input("부서/직책", value=sel_item.get('department', ''))
                    
                    e_linked_partner = ""
                    if e_role == "partner":
                        partners = get_partners()
                        e_linked_partner = st.selectbox("연동 거래처", ["선택하세요"] + partners, index=partners.index(sel_item['linked_partner']) + 1 if sel_item.get('linked_partner') in partners else 0)

                    e_permissions = st.multiselect("메뉴 접근 권한", all_permissions, default=sel_item.get('permissions', []))
                    
                    if st.form_submit_button("수정 저장"):
                        updates = {
                            "name": e_name,
                            "phone": e_phone,
                            "role": e_role,
                            "department": e_dept,
                            "permissions": e_permissions,
                            "linked_partner": e_linked_partner if e_role == "partner" and e_linked_partner != "선택하세요" else ""
                        }
                        db.collection("users").document(sel_id).update(updates)
                        st.success("수정되었습니다.")
                        st.rerun()
                
                st.divider()
                st.markdown("##### 관리 기능")
                c_adm1, c_adm2 = st.columns(2)
                if c_adm1.button("🔑 비밀번호 초기화 (0000)", key=f"reset_pw_{sel_id}"):
                    db.collection("users").document(sel_id).update({"password": "0000", "password_changed_at": firestore.DELETE_FIELD})
                    st.success(f"'{sel_item['name']}'님의 비밀번호가 '0000'으로 초기화되었습니다.")
                
                if c_adm2.button("🗑️ 이 사용자 삭제", type="primary", key=f"del_user_{sel_id}"):
                    if sel_id == st.session_state.get("user_id"):
                        st.error("현재 로그인된 계정은 삭제할 수 없습니다.")
                    else:
                        db.collection("users").document(sel_id).delete()
                        st.success(f"'{sel_item['name']}' 사용자가 삭제되었습니다.")
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
        
        # [NEW] 직인 이미지 업로드
        st.markdown("---")
        st.markdown("##### 🔴 직인(도장) 이미지")
        st.caption("거래명세서의 '공급자 성명' 란에 표시될 도장 이미지입니다. (배경이 투명한 PNG 파일 권장)")
        
        c_stamp1, c_stamp2 = st.columns([1, 2])
        current_stamp = data.get("stamp_img")
        delete_stamp = False
        
        with c_stamp1:
            if current_stamp:
                st.image(base64.b64decode(current_stamp), width=80, caption="현재 등록된 직인")
                delete_stamp = st.checkbox("직인 삭제", key="del_stamp_chk")
            else:
                st.info("등록된 직인이 없습니다.")
                
        with c_stamp2:
            new_stamp_file = st.file_uploader("이미지 업로드 (200KB 이하)", type=['png', 'jpg', 'jpeg'], key="stamp_uploader")

        # [NEW] 회사 로고 이미지 업로드
        st.markdown("---")
        st.markdown("##### 🏢 회사 로고 이미지")
        st.caption("거래명세서 좌측 상단에 표시될 로고 이미지입니다.")
        
        c_logo1, c_logo2 = st.columns([1, 2])
        current_logo = data.get("logo_img")
        delete_logo = False
        
        with c_logo1:
            if current_logo:
                st.image(base64.b64decode(current_logo), width=150, caption="현재 등록된 로고")
                delete_logo = st.checkbox("로고 삭제", key="del_logo_chk")
            else:
                st.info("등록된 로고가 없습니다.")
                
        with c_logo2:
            new_logo_file = st.file_uploader("로고 이미지 업로드 (200KB 이하)", type=['png', 'jpg', 'jpeg'], key="logo_uploader")

        if st.button("저장", type="primary"):
            new_data = {
                "name": name, "rep_name": rep_name, "biz_num": biz_num, 
                "address": address, "address_detail": addr_detail, # 상세주소 별도 저장 또는 합쳐서 저장 가능 (여기선 분리 저장 예시)
                "phone": phone, "fax": fax, "biz_type": biz_type, "biz_item": biz_item,
                "email": email, "bank_name": bank_name, "bank_account": bank_account, "note": note,
                "juso_api_key": juso_api_key,
                "app_title": app_title
            }
            
            # 직인 처리
            if new_stamp_file:
                if new_stamp_file.size > 200 * 1024:
                    st.error("직인 이미지 용량이 너무 큽니다. (200KB 이하 권장)")
                    st.stop()
                stamp_bytes = new_stamp_file.read()
                new_data["stamp_img"] = base64.b64encode(stamp_bytes).decode('utf-8')
            elif current_stamp and not delete_stamp:
                new_data["stamp_img"] = current_stamp
            else:
                new_data["stamp_img"] = None

            # 로고 처리
            if new_logo_file:
                if new_logo_file.size > 200 * 1024:
                    st.error("로고 이미지 용량이 너무 큽니다. (200KB 이하 권장)")
                    st.stop()
                logo_bytes = new_logo_file.read()
                new_data["logo_img"] = base64.b64encode(logo_bytes).decode('utf-8')
            elif current_logo and not delete_logo:
                new_data["logo_img"] = current_logo
            else:
                new_data["logo_img"] = None

            doc_ref.set(new_data)
            st.success("회사 정보가 저장되었습니다.")
            st.rerun()