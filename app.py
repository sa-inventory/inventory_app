import streamlit as st

# 1. 화면 기본 설정 (제목 등) - 반드시 다른 Streamlit 명령이나 커스텀 모듈 임포트보다 먼저 실행되어야 함
st.set_page_config(page_title="타올 생산 현황 관리", page_icon="logo.png", layout="wide")

import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import datetime
import json
import pandas as pd
import io
import uuid
import streamlit.components.v1 as components
# [NEW] 분리한 utils 파일에서 공통 함수 임포트
from utils import get_db, firestore, validate_password
from ui_orders import render_order_entry, render_order_status, render_partner_order_status
from ui_production_weaving import render_weaving
from ui_production_dyeing import render_dyeing
from ui_production_sewing import render_sewing
from ui_shipping import render_shipping_operations, render_shipping_status
from ui_inventory import render_inventory
from ui_basic_info import render_product_master, render_partners, render_machines, render_codes
from ui_system import render_users, render_my_profile, render_company_settings
from ui_statistics import render_statistics
from ui_board import render_notice_board, render_schedule

# [수정] CSS 스타일 정의 (관리자 여부에 따라 메뉴 표시/숨김 분기)
base_css = """
    <style>
        /* 메인 영역 상단 여백 줄이기 (기본값은 약 6rem) */
        .block-container {
            padding-top: 3rem !important;
        }
        /* [NEW] 사이드바 Expander 헤더 스타일링 (열려있는 경우 강조) */
        [data-testid="stSidebar"] details[open] > summary {
            background-color: #e6f3ff !important;
            color: #1c62b0 !important;
            font-weight: bold !important;
            border-radius: 0.5rem;
        }
        /* [NEW] 탭 스타일링 (선택된 탭 강조) */
        button[data-baseweb="tab"][aria-selected="true"] {
            color: #1c62b0 !important;
            font-weight: bold !important;
            font-size: 1.1rem !important;
        }
        /* [NEW] 사이드바 하위 메뉴 (Expander 내부 버튼) 글자 크기 축소 */
        [data-testid="stSidebar"] details button p {
            font-size: 0.9rem !important;
        }
"""

# 관리자가 아니면(일반 사용자, 파트너, 비로그인) Streamlit 기본 메뉴 숨김
if st.session_state.get("role") != "admin":
    base_css += """
        /* [NEW] 보안 및 깔끔한 화면을 위해 Streamlit 기본 메뉴 숨기기 */
        
        /* 1. 상단 데코레이션 바 숨김 */
        [data-testid="stDecoration"] {
            display: none !important;
        }
        
        /* 2. 우측 상단 툴바(점 3개 메뉴, 배포 버튼 등) 숨김 */
        [data-testid="stToolbar"] {
            display: none !important;
        }
        
        /* 3. 푸터 숨김 */
        footer {
            display: none !important;
        }
    """

base_css += "</style>"
st.markdown(base_css, unsafe_allow_html=True)

with st.spinner("시스템 초기화 및 DB 연결 중..."):
    db = get_db()

# --- 로그인 기능 추가 ---
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    st.session_state["role"] = None

# 로그인 화면 처리
if not st.session_state["logged_in"]:
    # [NEW] 회사 로고 및 제목 가져오기
    try:
        comp_doc = db.collection("settings").document("company_info").get()
        if comp_doc.exists:
            comp_data = comp_doc.to_dict()
            login_logo = comp_data.get("logo_img")
            # [NEW] 로그인 화면 디자인 설정 적용
            lg_logo_width = comp_data.get("lg_logo_width", 120)
            lg_title_size = comp_data.get("lg_title_size", 2.5)
            lg_title_html = comp_data.get("lg_title_html", comp_data.get("app_title", "세안타올 생산 관리"))
        else:
            login_logo = None
            lg_title_html = "세안타올 생산 관리"
            lg_logo_width = 120
            lg_title_size = 2.5
    except:
        login_logo = None
        lg_title_html = "세안타올 생산 관리"
        lg_logo_width = 120
        lg_title_size = 2.5

    if login_logo:
        st.markdown(
            f"""<div style="display: flex; justify-content: center; align-items: center; margin-bottom: 30px; flex-wrap: wrap;">
                <img src="data:image/png;base64,{login_logo}" style="width: {lg_logo_width}px; max-height: 200px; margin-right: 20px;">
                <h1 style='margin: 0; font-size: {lg_title_size}rem; text-align: center; line-height: 1.2;'>{lg_title_html}</h1>
            </div>""",
            unsafe_allow_html=True
        )
    else:
        st.markdown(f"<h1 style='text-align: center; font-size: {lg_title_size}rem;'>{lg_title_html}</h1>", unsafe_allow_html=True)
    
    # [NEW] 아이디 입력 후 엔터 시 비밀번호 필드로 포커스 이동 (JS 주입)
    components.html("""
    <script>
        const doc = window.parent.document;
        const observer = new MutationObserver(() => {
            const idInputs = doc.querySelectorAll('input[aria-label="아이디"]');
            const pwInputs = doc.querySelectorAll('input[aria-label="비밀번호"]');
            
            idInputs.forEach((idInput, idx) => {
                if (pwInputs[idx] && !idInput.dataset.hasEnterListener) {
                    idInput.dataset.hasEnterListener = "true";
                    idInput.addEventListener('keydown', (e) => {
                        if (e.key === 'Enter') {
                            e.preventDefault();
                            e.stopPropagation();
                            pwInputs[idx].focus();
                        }
                    });
                }
            });
        });
        observer.observe(doc.body, { childList: true, subtree: true });
    </script>
    """, height=0, width=0)
    
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        tab_staff, tab_partner = st.tabs(["직원 로그인", "거래처 로그인"])
        
        with tab_staff:
            with st.form("login_form"):
                st.subheader("직원 로그인")
                login_id = st.text_input("아이디", placeholder="아이디를 입력하세요")
                login_pw = st.text_input("비밀번호", type="password", placeholder="비밀번호를 입력하세요")
                
                if st.form_submit_button("로그인", use_container_width=True):
                    if not login_id:
                        st.error("아이디를 입력해주세요.")
                        st.stop()
                    
                    try:
                        user_doc = db.collection("users").document(login_id).get()
                    except Exception:
                        st.error("⚠️ 현재 시스템 접속량이 많아(일일 사용량 초과) 로그인이 제한됩니다. 내일 오전 9시 이후 다시 시도해주세요.")
                        st.stop()

                    if user_doc.exists:
                        user_data = user_doc.to_dict()
                        if user_data.get("password") == login_pw:
                            # [NEW] 직원 로그인 탭에서 거래처 계정 로그인 차단
                            if user_data.get("role") == "partner":
                                st.error("거래처 계정입니다. '거래처 로그인' 탭을 이용해주세요.")
                            else:
                                st.session_state["logged_in"] = True
                                st.session_state["role"] = user_data.get("role", "user")
                                st.session_state["user_name"] = user_data.get("name", login_id)
                                st.session_state["user_id"] = login_id
                                st.session_state["department"] = user_data.get("department", "")
                                st.session_state["linked_partner"] = user_data.get("linked_partner", "")
                                # [NEW] 권한 목록 세션 저장
                                st.session_state["permissions"] = user_data.get("permissions") or []
                                st.session_state["auto_logout_minutes"] = user_data.get("auto_logout_minutes", 60)
                                st.session_state["login_time"] = datetime.datetime.now()
                                
                                # [NEW] 비밀번호 만료 체크 (90일)
                                pw_changed = user_data.get("password_changed_at")
                                if pw_changed:
                                    if hasattr(pw_changed, 'tzinfo') and pw_changed.tzinfo:
                                        pw_changed = pw_changed.replace(tzinfo=None)
                                    if (datetime.datetime.now() - pw_changed).days >= 90:
                                        st.session_state["password_expired"] = True
                                else:
                                    # 변경 기록이 없으면 현재 시간으로 초기화 (바로 만료시키지 않음)
                                    db.collection("users").document(login_id).update({"password_changed_at": datetime.datetime.now()})
                                
                                # [NEW] 비밀번호 초기화 상태 체크 (0000)
                                if user_data.get("password") == "0000":
                                    st.session_state["password_reset_needed"] = True

                                # [수정] 로그인 시 기본 메뉴 설정 (권한 기반)
                                if "current_menu" in st.session_state:
                                    del st.session_state["current_menu"]
                                
                                st.session_state["current_menu"] = "공지사항"
                                if "current_sub_menu" in st.session_state:
                                    del st.session_state["current_sub_menu"]
                                st.rerun()
                        else:
                            st.error("비밀번호가 일치하지 않습니다.")
                    else:
                        st.error("등록되지 않은 아이디입니다.")

        with tab_partner:
            with st.form("partner_login_form"):
                st.subheader("거래처 로그인")
                # [수정] 보안을 위해 거래처 목록 선택 대신 아이디/비밀번호 입력 방식으로 변경
                p_id = st.text_input("아이디", placeholder="아이디를 입력하세요")
                p_pw = st.text_input("비밀번호", type="password", placeholder="비밀번호를 입력하세요")
                
                if st.form_submit_button("로그인", use_container_width=True):
                    if not p_id:
                        st.error("아이디를 입력해주세요.")
                        st.stop()
                    
                    try:
                        user_doc = db.collection("users").document(p_id).get()
                    except Exception:
                        st.error("⚠️ 현재 시스템 접속량이 많아(일일 사용량 초과) 로그인이 제한됩니다. 내일 오전 9시 이후 다시 시도해주세요.")
                        st.stop()

                    if user_doc.exists:
                        user_data = user_doc.to_dict()
                        # 거래처 계정인지 확인
                        if user_data.get("role") == "partner":
                            if user_data.get("password") == p_pw:
                                st.session_state["logged_in"] = True
                                st.session_state["role"] = "partner"
                                st.session_state["user_name"] = user_data.get("name")
                                st.session_state["user_id"] = p_id
                                st.session_state["linked_partner"] = user_data.get("linked_partner")
                                st.session_state["auto_logout_minutes"] = user_data.get("auto_logout_minutes", 60)
                                st.session_state["login_time"] = datetime.datetime.now()
                                st.session_state["permissions"] = user_data.get("permissions") or []
                                
                                # [NEW] 비밀번호 만료 체크 (90일)
                                pw_changed = user_data.get("password_changed_at")
                                if pw_changed:
                                    if hasattr(pw_changed, 'tzinfo') and pw_changed.tzinfo:
                                        pw_changed = pw_changed.replace(tzinfo=None)
                                    if (datetime.datetime.now() - pw_changed).days >= 90:
                                        st.session_state["password_expired"] = True
                                else:
                                    db.collection("users").document(p_id).update({"password_changed_at": datetime.datetime.now()})
                                
                                # [NEW] 비밀번호 초기화 상태 체크 (0000)
                                if user_data.get("password") == "0000":
                                    st.session_state["password_reset_needed"] = True

                                # [수정] 로그인 시 기본 메뉴 설정 (권한 기반)
                                if "current_menu" in st.session_state:
                                    del st.session_state["current_menu"]
                                
                                user_perms = user_data.get("permissions", [])
                                st.session_state["current_menu"] = user_perms[0] if user_perms else "발주현황(거래처)"
                                if "current_sub_menu" in st.session_state:
                                    del st.session_state["current_sub_menu"]
                                st.rerun()
                            else:
                                st.error("비밀번호가 일치하지 않습니다.")
                        else:
                            st.error("거래처 계정이 아닙니다. 직원 로그인 탭을 이용해주세요.")
                    else:
                        st.error("등록되지 않은 아이디입니다.")
    
    # [NEW] 강제 로그아웃 처리 (URL 파라미터 감지)
    if st.query_params.get("logout"):
        st.query_params.clear()
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

    st.stop()

# [NEW] 브라우저 탭 제목 동적 변경 (사용자 설정 반영)
try:
    c_doc = db.collection("settings").document("company_info").get()
    if c_doc.exists:
        app_title = c_doc.to_dict().get("app_title", "타올 생산 현황 관리")
    else:
        app_title = "타올 생산 현황 관리"
except:
    app_title = "타올 생산 현황 관리"

components.html(f"""
    <script>
        const title = "{app_title}";
        window.parent.document.title = title;
        
        // Title Observer to prevent "- Streamlit" suffix
        new MutationObserver(function(mutations) {{
            if (window.parent.document.title !== title) {{
                window.parent.document.title = title;
            }}
        }}).observe(window.parent.document.querySelector('title'), {{ childList: true }});
    </script>
""", height=0)

# 3. [왼쪽 사이드바] 상품 등록 기능
with st.sidebar:
    # [NEW] 비밀번호 만료 시 사이드바 숨김 처리 등을 위해 체크
    if st.session_state.get("password_expired"):
        st.warning("비밀번호 변경이 필요합니다.")
        st.stop() # 사이드바 렌더링 중단

    # [NEW] 회사 정보 가져오기 (상호명 표시용)
    try:
        comp_info_ref = db.collection("settings").document("company_info").get()
        if comp_info_ref.exists:
            comp_data = comp_info_ref.to_dict()
            logo_img = comp_data.get("logo_img")
            
            # [NEW] 사이드바 디자인 설정 적용
            sb_logo_width = comp_data.get("sb_logo_width", 45)
            sb_title_size = comp_data.get("sb_title_size", 2.2)
            sb_title_html = comp_data.get("sb_title_html", comp_data.get("name", "세안타올"))
            sb_subtitle = comp_data.get("sb_subtitle", "생산관리 시스템")
        else:
            logo_img = None
            sb_title_html = "세안타올"
            sb_logo_width = 45
            sb_title_size = 2.2
            sb_subtitle = "생산관리 시스템"
    except:
        logo_img = None
        sb_title_html = "세안타올"
        sb_logo_width = 45
        sb_title_size = 2.2
        sb_subtitle = "생산관리 시스템"

    # 로고 이미지 처리
    if logo_img:
        # [수정] 로고와 제목 배치 유연성 확보 (flex-wrap)
        st.markdown(f"""
        <div style='text-align: center; margin-bottom: 20px;'>
            <div style='display: flex; align-items: center; justify-content: center; flex-wrap: wrap;'>
                <img src="data:image/png;base64,{logo_img}" style="width: {sb_logo_width}px; max-height: 100px; margin-right: 10px;">
                <h1 style='margin:0; font-size: {sb_title_size}rem; font-weight: 700; line-height: 1.2;'>{sb_title_html}</h1>
            </div>
            <h3 style='margin:0; font-size: 1.5rem; color: #333; font-weight: 600; margin-top: 5px;'>{sb_subtitle}</h3>
        </div>
    """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div style='text-align: center; margin-bottom: 20px;'>
            <h1 style='margin:0; font-size: {sb_title_size}rem; font-weight: 700;'>🏢 {sb_title_html}</h1>
            <h3 style='margin:0; font-size: 1.5rem; color: #333; font-weight: 600; margin-top: 5px;'>{sb_subtitle}</h3>
        </div>
    """, unsafe_allow_html=True)

    user_display = st.session_state.get("user_name", st.session_state.get("role"))
    st.write(f"환영합니다.  **{user_display}**님!")
    
    st.divider()
    
    # 메뉴 선택 기능 추가
    if "current_menu" not in st.session_state:
        # [수정] 새로고침 시에도 권한 기반 기본 메뉴 설정
        if st.session_state.get("role") == "partner":
            perms = st.session_state.get("permissions", [])
            st.session_state["current_menu"] = perms[0] if perms else "발주현황(거래처)"
        else:
            # 직원은 공지사항이 기본이지만, 권한이 없을 수도 있으므로 체크
            perms = st.session_state.get("permissions", [])
            st.session_state["current_menu"] = "공지사항" # 공지사항은 보통 공통 권한
    
    # [NEW] 하위 메뉴 상태 초기화
    if "current_sub_menu" not in st.session_state:
        st.session_state["current_sub_menu"] = None

    # [NEW] 권한 확인 헬퍼 함수
    def check_access(menu_name):
        # 관리자는 모든 메뉴 접근 가능
        if st.session_state.get("role") == "admin": return True
        
        # [FIX] 파트너 계정인데 권한 목록이 비어있는 경우 (등록 오류 등) 기본 메뉴 접근 허용
        if st.session_state.get("role") == "partner" and not st.session_state.get("permissions"):
            return menu_name in ["발주현황(거래처)", "재고현황(거래처)"]
            
        # 사용자는 permissions 목록에 있는 메뉴만 접근 가능
        user_perms = st.session_state.get("permissions", [])
        
        # [FIX] 파트너 계정의 경우, 구버전 권한(직원용 메뉴명) 호환성 처리
        if st.session_state.get("role") == "partner":
            if menu_name == "발주현황(거래처)" and ("발주현황" in user_perms or "발주현황(거래처)" in user_perms):
                return True
            if menu_name == "재고현황(거래처)" and ("재고현황" in user_perms or "재고현황(거래처)" in user_perms):
                return True
                
        return menu_name in user_perms

    # [NEW] 메뉴 아이템 생성 헬퍼 함수
    def menu_item(label, main_menu, sub_menu=None):
        # sub_menu가 없으면 label을 사용
        effective_sub_menu = sub_menu if sub_menu is not None else label
        
        # 현재 선택된 메뉴와 같으면 강조 스타일 적용
        is_selected = (st.session_state.get("current_menu") == main_menu and 
                       st.session_state.get("current_sub_menu") == effective_sub_menu)
        
        # [수정] 선택된 메뉴 강조 (Primary 버튼 사용)
        btn_type = "primary" if is_selected else "secondary"
        
        if st.button(label, use_container_width=True, key=f"menu_{main_menu}_{effective_sub_menu}", type=btn_type):
            # [FIX] 메뉴 이동 시 열려있는 주소 검색 팝업 닫기 (상태 초기화)
            for key in ["show_partner_addr_dialog", "show_company_addr_dialog", "show_order_addr_dialog"]:
                if key in st.session_state:
                    st.session_state[key] = False
            
            st.session_state["current_menu"] = main_menu
            st.session_state["current_sub_menu"] = effective_sub_menu
            
            # 공지사항 메뉴 클릭 시 특별 처리
            if main_menu == "공지사항":
                st.session_state["notice_view_mode"] = "list"
                st.session_state["selected_post_id"] = None
                st.session_state["notice_expander_state"] = False
                st.query_params.clear()
            st.rerun()

    # [NEW] 거래처(partner) 계정일 경우 메뉴 간소화
    if st.session_state.get("role") == "partner":
        st.info(f"**{st.session_state.get('linked_partner')}** 전용")
        # [수정] 권한이 있는 메뉴만 표시
        if check_access("발주현황(거래처)"):
            menu_item("발주 현황 조회", "발주현황(거래처)")
        if check_access("재고현황(거래처)"):
            menu_item("재고 현황 조회", "재고현황(거래처)")
            
    else:
        # [NEW] 직원용 전체 메뉴 구조
        cm = st.session_state.get("current_menu")
        
        # [NEW] 메뉴 버튼 스타일링 (위치 기반 지정)
        # [수정] CSS 방식 대신 이모지를 사용하여 직관적으로 구분 (더 안정적임)
        menu_item("📢 공지사항", "공지사항")
        menu_item("🗓️ 업무일정", "업무일정")
        
        st.divider()

        if check_access("발주서접수"):
            menu_item("📝 발주서접수", "발주서접수", "개별 접수")
            # [수정] 구분선이 잘 보이도록 색상(#ccc)을 진하게 하고 마진 조정
            st.markdown("<hr style='margin: 1rem 0; border: none; border-top: 1px solid #ccc;' />", unsafe_allow_html=True)

        if check_access("발주현황"):
            with st.expander("발주현황", expanded=(cm == "발주현황")):
                menu_item("발주현황 조회", "발주현황")
                if st.session_state.get("role") == "admin":
                    menu_item("발주내역삭제(엑셀업로드)", "발주현황")

        # [수정] 하위 메뉴 권한이 하나라도 있을 때만 상위 메뉴 표시
        has_production_access = check_access("제직현황") or check_access("제직조회") or check_access("염색현황") or check_access("봉제현황")
        if has_production_access:
            with st.expander("생산관리", expanded=(cm in ["제직현황", "제직조회", "염색현황", "봉제현황"])):
                if check_access("제직현황"):
                    with st.expander("제직현황", expanded=(cm == "제직현황")):
                        menu_item("제직대기 목록", "제직현황")
                        menu_item("제직중 목록", "제직현황")
                        menu_item("제직완료 목록", "제직현황")
                        menu_item("작업일지", "제직현황")
                        menu_item("생산일지", "제직현황")
                if check_access("제직조회"):
                    with st.expander("제직조회", expanded=(cm == "제직조회")):
                        menu_item("제직대기 목록", "제직조회")
                        menu_item("제직중 목록", "제직조회")
                        menu_item("제직완료 목록", "제직조회")
                if check_access("염색현황"):
                    with st.expander("염색현황", expanded=(cm == "염색현황")):
                        menu_item("염색 대기 목록", "염색현황")
                        menu_item("염색중 목록", "염색현황")
                        menu_item("염색 완료 목록", "염색현황")
                        menu_item("색번 설정", "염색현황")
                if check_access("봉제현황"):
                    with st.expander("봉제현황", expanded=(cm == "봉제현황")):
                        menu_item("봉제 대기 목록", "봉제현황")
                        menu_item("봉제중 목록", "봉제현황")
                        menu_item("봉제 완료 목록", "봉제현황")

        # [수정] 출고관리 메뉴 (출고작업 + 출고현황)
        if check_access("출고현황"):
            with st.expander("출고관리", expanded=(cm in ["출고작업", "출고현황"])):
                menu_item("출고작업", "출고작업")
                with st.expander("출고현황", expanded=(cm == "출고현황")):
                    menu_item("출고 완료 내역 (조회/명세서)", "출고현황")
                    menu_item("배송/운임 통계", "출고현황")

        # [수정] 재고관리 메뉴 (재고현황 분리)
        if check_access("재고현황"):
            with st.expander("재고관리", expanded=(cm == "재고현황")):
                menu_item("재고 현황 조회", "재고현황")
                menu_item("재고 임의 등록", "재고현황")

        if st.session_state.get("role") == "admin":
            with st.expander("내역조회", expanded=(cm == "내역조회")):
                menu_item("발주내역", "내역조회")
                menu_item("제직내역", "내역조회")
                menu_item("염색내역", "내역조회")
                menu_item("봉제내역", "내역조회")
                menu_item("출고/운임내역", "내역조회")

        # [수정] 하위 메뉴 권한이 하나라도 있을 때만 상위 메뉴 표시
        has_basic_info_access = check_access("제품 관리") or check_access("거래처관리") or check_access("제직기관리") or check_access("제품코드설정")
        if has_basic_info_access:
            with st.expander("기초정보관리", expanded=(cm in ["제품 관리", "거래처관리", "제직기관리", "제품코드설정"])):
                # [수정] 제품 관리 및 제품코드설정 통합
                if check_access("제품 관리") or check_access("제품코드설정"):
                    with st.expander("제품 관리", expanded=(cm == "제품 관리")):
                        if check_access("제품 관리"):
                            menu_item("제품 목록", "제품 관리")
                            menu_item("제품 등록", "제품 관리")
                        
                        if check_access("제품코드설정"):
                            csm = st.session_state.get("current_sub_menu")
                            with st.expander("제품코드설정", expanded=(csm in ["제품 종류", "사종", "중량", "사이즈"])):
                                menu_item("제품 종류", "제품 관리")
                                menu_item("사종", "제품 관리")
                                menu_item("중량", "제품 관리")
                                menu_item("사이즈", "제품 관리")

                if check_access("거래처관리"):
                    with st.expander("거래처관리", expanded=(cm == "거래처관리")):
                        menu_item("거래처 목록", "거래처관리")
                        menu_item("거래처 등록", "거래처관리")
                        menu_item("거래처 구분 관리", "거래처관리")
                        menu_item("배송방법 관리", "거래처관리")
                if check_access("제직기관리"):
                    with st.expander("제직기관리", expanded=(cm == "제직기관리")):
                        menu_item("제직기 목록", "제직기관리")
                        menu_item("제직기 등록", "제직기관리")

        if st.session_state.get("role") == "admin":
            with st.expander("시스템관리", expanded=(cm in ["사용자 관리", "회사정보 관리"])):
                with st.expander("사용자 관리", expanded=(cm == "사용자 관리")):
                    menu_item("사용자 목록", "사용자 관리")
                    menu_item("사용자 등록", "사용자 관리")
                with st.expander("회사정보 관리", expanded=(cm == "회사정보 관리")):
                    menu_item("회사정보 조회", "회사정보 관리")
                    menu_item("정보 수정", "회사정보 관리")
    
    # [수정] 하단 여백 축소 (50px -> 10px)
    st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)

    st.divider()
    
    menu_item("로그인 정보 설정", "로그인 정보 설정")
    
    if st.button("로그아웃", use_container_width=True):

        st.session_state["logged_in"] = False
        st.session_state["role"] = None
        if "user_name" in st.session_state:
            del st.session_state["user_name"]
        if "current_menu" in st.session_state:
            del st.session_state["current_menu"]
        # [수정] 로그아웃 시 달력 상태 초기화
        if "cal_year" in st.session_state: del st.session_state["cal_year"]
        if "cal_month" in st.session_state: del st.session_state["cal_month"]

        st.rerun()
 
menu = st.session_state["current_menu"]
sub_menu = st.session_state.get("current_sub_menu")

# [NEW] 비밀번호 만료 또는 초기화 시 강제 변경 화면 표시
if st.session_state.get("password_expired") or st.session_state.get("password_reset_needed"):
    if st.session_state.get("password_reset_needed"):
        st.error("🔒 비밀번호 초기화 안내")
        st.warning("관리자에 의해 비밀번호가 초기화되었습니다. 보안을 위해 새로운 비밀번호를 설정해주세요.")
    else:
        st.error("🔒 비밀번호 만료 안내")
        st.warning("비밀번호를 변경한 지 3개월(90일)이 지났습니다. 보안을 위해 비밀번호를 변경해주세요.")
    
    with st.form("force_pw_change_form"):
        new_pw = st.text_input("새 비밀번호", type="password")
        new_pw_chk = st.text_input("새 비밀번호 확인", type="password")
        
        if st.form_submit_button("비밀번호 변경 및 로그인"):
            if new_pw and new_pw == new_pw_chk:
                # [NEW] 비밀번호 정책 검증
                is_valid, err_msg = validate_password(new_pw)
                if not is_valid:
                    st.error(err_msg)
                    st.stop()
                
                uid = st.session_state["user_id"]
                db.collection("users").document(uid).update({
                    "password": new_pw,
                    "password_changed_at": datetime.datetime.now()
                })
                st.session_state["password_expired"] = False
                st.session_state["password_reset_needed"] = False
                st.success("비밀번호가 변경되었습니다.")
                st.rerun()
            elif not new_pw:
                st.error("비밀번호를 입력해주세요.")
            else:
                st.error("비밀번호가 일치하지 않습니다.")
    st.stop() # 메인 화면 렌더링 중단

# [NEW] 자동 로그아웃 타이머 및 감지 스크립트 주입
if st.session_state.get("logged_in"):
    timeout_min = st.session_state.get("auto_logout_minutes", 60)
    login_time = st.session_state.get("login_time", datetime.datetime.now())
    login_time_str = login_time.strftime("%Y년 %m월 %d일 %H시 %M분")
    
    # [NEW] 사용자별 고유 키 생성을 위해 user_id 사용
    user_id = st.session_state.get("user_id", "unknown")
    
    js_code = f"""
    <script>
        (function() {{
            const loginTimeStr = "{login_time_str}";
            const timeoutMinutes = {timeout_min};
            const timeoutMs = timeoutMinutes * 60 * 1000;
            const storageKey = "lastActivity_" + "{user_id}"; // 사용자별 키 분리

            // [FIX] 초기화: 저장된 활동 시간이 없으면 현재 시간으로 설정 (Local Storage 사용)
            if (!localStorage.getItem(storageKey)) {{
                localStorage.setItem(storageKey, Date.now());
            }}
            
            // [NEW] 로그아웃 체크 함수 분리
            function checkLogout() {{
                const now = Date.now();
                const lastActivity = parseInt(localStorage.getItem(storageKey) || now);
                const idleMs = now - lastActivity;
                
                if (idleMs > timeoutMs) {{
                    localStorage.removeItem(storageKey);
                    if (!window.parent.location.href.includes('logout=true')) {{
                        window.parent.location.href = window.parent.location.pathname + '?logout=true';
                    }}
                    return true;
                }}
                return false;
            }}

            function updateTimer() {{
                // [FIX] 타이머 갱신 시마다 로그아웃 조건 체크
                if (checkLogout()) return;

                const now = Date.now();
                
                const idleMs = now - lastActivity;
                const remainingMs = timeoutMs - idleMs;
                
                // Format time (1분 이상이면 분 단위, 미만이면 초 단위)
                let timeStr = "";
                if (remainingMs > 60000) {{
                    const totalMin = Math.ceil(remainingMs / 60000);
                    const h = Math.floor(totalMin / 60);
                    const m = totalMin % 60;
                    timeStr = h + "시간 " + m + "분";
                }} else {{
                    timeStr = Math.ceil(remainingMs / 1000) + "초";
                }}
                
                // Update display
                let timerDiv = window.parent.document.getElementById('auto-logout-timer');
                if (!timerDiv) {{
                    timerDiv = window.parent.document.createElement('div');
                    timerDiv.id = 'auto-logout-timer';
                    timerDiv.style.position = 'fixed';
                    timerDiv.style.top = '60px'; 
                    timerDiv.style.right = '20px';
                    timerDiv.style.backgroundColor = 'rgba(255, 255, 255, 0.8)';
                    timerDiv.style.color = '#000000';
                    timerDiv.style.padding = '4px 8px';
                    timerDiv.style.borderRadius = '4px';
                    timerDiv.style.fontSize = '12px';
                    timerDiv.style.fontWeight = 'normal';
                    timerDiv.style.zIndex = '999999';
                    timerDiv.style.pointerEvents = 'none';
                    timerDiv.style.lineHeight = '1.3';
                    window.parent.document.body.appendChild(timerDiv);
                }}
                timerDiv.innerHTML = '접속시간 ' + loginTimeStr + '<br>[미조작 시 로그아웃] ' + timeStr + ' 남음';
            }}
            
            function resetTimer() {{
                if (checkLogout()) return;
                localStorage.setItem(storageKey, Date.now());
                updateTimer();
            }}
            
            // Attach events to parent window
            const doc = window.parent.document;
            doc.addEventListener('mousemove', resetTimer);
            doc.addEventListener('keydown', resetTimer);
            doc.addEventListener('click', resetTimer);
            doc.addEventListener('scroll', resetTimer);
            
            // [NEW] 탭 활성화/비활성화 감지 (절전모드 복귀 시 체크 강화)
            doc.addEventListener('visibilitychange', function() {{
                if (!doc.hidden) {{
                    checkLogout();
                    updateTimer();
                }}
            }});
            
            // Interval
            if (!window.logoutInterval) {{
                window.logoutInterval = setInterval(updateTimer, 1000);
            }}
            
            // 초기 1회 실행
            checkLogout();
            updateTimer();
        }})();
    </script>
    """
    components.html(js_code, height=0)

# 4. [메인 화면] 메뉴별 기능 구현
if menu == "공지사항":
    render_notice_board(db)
elif menu == "업무일정":
    render_schedule(db)
elif menu == "발주서접수":
    render_order_entry(db, sub_menu)
elif menu == "발주현황":
    render_order_status(db, sub_menu)
elif menu == "발주현황(거래처)":
    render_partner_order_status(db)
elif menu == "재고현황(거래처)":
    render_inventory(db, "재고 현황 조회")

elif menu == "제직현황":
    render_weaving(db, sub_menu)
elif menu == "제직조회":
    render_weaving(db, sub_menu, readonly=True)
elif menu == "염색현황":
    render_dyeing(db, sub_menu)
elif menu == "봉제현황":
    render_sewing(db, sub_menu)
elif menu == "출고작업":
    render_shipping_operations(db, sub_menu)
elif menu == "출고현황":
    render_shipping_status(db, sub_menu)
elif menu == "재고현황":
    render_inventory(db, sub_menu)
elif menu == "내역조회":
    render_statistics(db, sub_menu)
elif menu == "제품 관리":
    render_product_master(db, sub_menu)
elif menu == "거래처관리":
    render_partners(db, sub_menu)
elif menu == "제직기관리":
    render_machines(db, sub_menu)
elif menu == "사용자 관리":
    render_users(db, sub_menu)
elif menu == "회사정보 관리":
    render_company_settings(db, sub_menu)
elif menu == "로그인 정보 설정":
    render_my_profile(db)
else:
    st.header(f"{menu}")
    st.info(f"'{menu}' 기능은 추후 업데이트될 예정입니다.")
