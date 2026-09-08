import datetime
import altair as alt
import pandas as pd
import requests
import streamlit as st
import pytz

# ==========================================
# 1. 페이지 기본 설정 및 디자인
# ==========================================
st.set_page_config(
    page_title="일별 박스오피스 검색",
    page_icon="🎬",
    layout="wide"
)

# ==========================================
# 2. 기준 날짜 계산 및 달력 입력 (KST 기준)
# ==========================================
# 배포 서버(Streamlit Cloud)의 시각이 UTC여도 한국 시간 기준으로 계산합니다.
kst = pytz.timezone("Asia/Seoul")
today_kst = datetime.datetime.now(kst).date()
yesterday_kst = today_kst - datetime.timedelta(days=1)

st.title("🎬 일별 박스오피스")

# 달력에서 날짜 선택 (최대 선택 가능 날짜: 어제)
selected_date = st.date_input(
    label="조회할 날짜를 선택하세요 (오늘 날짜는 아직 집계 전입니다)",
    value=yesterday_kst,
    max_value=yesterday_kst,
    min_value=datetime.date(2004, 1, 1) # KOBIS API 서비스 개시 시점 기준
)

target_date_str = selected_date.strftime("%Y%m%d")      # API 요청용 (예: 20260907)
display_date_str = selected_date.strftime("%Y년 %m월 %d일") # 화면 표시용 (예: 2026년 09월 07일)

st.caption(f" 기준 날짜: **{display_date_str}**")

# ==========================================
# 3. KOBIS API 데이터 불러오기 함수 (캐싱 적용)
# ==========================================
# ttl=3600: 동일한 날짜 데이터는 1시간(3600초) 동안 메모리에 기억합니다.
@st.cache_data(ttl=3600)
def fetch_daily_boxoffice(target_dt: str):
    # Streamlit Secrets(비밀 금고)에서 인증키 불러오기
    if "KOBIS_KEY" not in st.secrets:
        return None, "secrets에 'KOBIS_KEY'가 설정되지 않았습니다. Secrets 설정을 확인해 주세요."
    
    api_key = st.secrets["KOBIS_KEY"]
    url = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"
    params = {
        "key": api_key,
        "targetDt": target_dt
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status() # HTTP 요청 실패 시 예외 발생
        data = response.json()

        # 오류 응답 처리 1: API 키 오류 시 faultInfo 상자가 반환됨 (HTTP status는 200)
        if "faultInfo" in data:
            message = data["faultInfo"].get("message", "알 수 없는 오류가 발생했습니다.")
            return None, f"KOBIS API 오류: {message} (발급받은 인증키를 확인해 주세요.)"

        # 오류 응답 처리 2: 데이터 구조 검증 및 빈 목록 처리
        box_office_result = data.get("boxOfficeResult", {})
        daily_list = box_office_result.get("dailyBoxOfficeList", [])

        if not daily_list:
            return None, "그날은 아직 집계 전입니다."

        # 정상 데이터 반환
        return daily_list, None

    except requests.exceptions.RequestException as e:
        return None, f"네트워크 요청에 실패했습니다: {e}"
    except Exception as e:
        return None, f"데이터를 처리하는 중 오류가 발생했습니다: {e}"

# API 호출 실행
raw_data, error_msg = fetch_daily_boxoffice(target_date_str)

# ==========================================
# 4. 에러 및 안내 메시지 출력
# ==========================================
if error_msg:
    if error_msg == "그날은 아직 집계 전입니다.":
        st.warning(f"⚠️ {display_date_str} - {error_msg}")
    else:
        st.error(error_msg)
        st.info(
            """
            💡 **확인해 보세요!**
            1. **Streamlit App Settings -> Secrets** 메뉴에 `KOBIS_KEY = "발급받은키"` 형태로 등록되어 있는지 확인하세요.
            2. KOBIS 영화관입장권통합전산망에서 발급받은 키가 유효한지 확인하세요.
            3. 인터넷 연결 상태나 KOBIS API 서버 점검 여부를 확인해 주세요.
            """
        )
    st.stop() # 이후 코드 실행 중단

# ==========================================
# 5. 데이터 전처리 (문자열 -> 숫자 변환 및 가공)
# ==========================================
df = pd.DataFrame(raw_data)

# 숫자형으로 변환할 컬럼 지정
numeric_columns = ["rank", "audiCnt", "audiAcc", "scrnCnt", "showCnt", "rankInten"]
for col in numeric_columns:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

# 순위 정렬
df = df.sort_values(by="rank").reset_index(drop=True)

# 1) 순위 증감 텍스트 변환 (rankOldAndNew 값 반영)
def format_rank_inten(row):
    if row.get("rankOldAndNew") == "NEW":
        return "🆕 NEW"
    inten = row["rankInten"]
    if inten > 0:
        return f"🔺 {int(inten)}"  # 순위 상승 (빨간 위 화살표)
    elif inten < 0:
        return f"🔹 {int(abs(inten))}"  # 순위 하락 (파란 아래 화살표)
    else:
        return "-"

df["rankIntenDisplay"] = df.apply(format_rank_inten, axis=1)

# 2) 누적 관객 100만 이상 트로피 표기
def format_movie_title(row):
    title = row["movieNm"]
    if row["audiAcc"] >= 1_000_000:
        return f"{title} 🏆"
    return title

df["displayMovieNm"] = df.apply(format_movie_title, axis=1)

# ==========================================
# 6. 1위 영화 하이라이트 (지표 카드 3장)
# ==========================================
if not df.empty:
    top_1 = df.iloc[0]
    
    st.subheader(f"🥇 1위: {top_1['displayMovieNm']}")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(
            label="당일 관객 수",
            value=f"{int(top_1['audiCnt']):,} 명"
        )
    with col2:
        st.metric(
            label="누적 관객 수",
            value=f"{int(top_1['audiAcc']):,} 명"
        )
    with col3:
        st.metric(
            label="스크린 수",
            value=f"{int(top_1['scrnCnt']):,} 개"
        )

st.markdown("---")

# ==========================================
# 7. 관객 수 상위 5편 막대그래프
# ==========================================
st.subheader("📊 관객 수 상위 5개 영화")

top_5_df = df.head(5).copy()

# 막대그래프 생성 (Altair)
chart = (
    alt.Chart(top_5_df)
    .mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5)
    .encode(
        x=alt.X("movieNm:N", title="영화명", sort="-y", axis=alt.Axis(labelAngle=-15)),
        y=alt.Y("audiCnt:Q", title="관객 수 (명)"),
        color=alt.Color("movieNm:N", legend=None),
        tooltip=[
            alt.Tooltip("movieNm:N", title="영화명"),
            alt.Tooltip("audiCnt:Q", title="일일 관객수", format=","),
            alt.Tooltip("audiAcc:Q", title="누적 관객수", format=",")
        ]
    )
    .properties(height=350)
)

st.altair_chart(chart, use_container_width=True)

st.markdown("---")

# ==========================================
# 8. 전체 순위 표 (데이터프레임)
# ==========================================
st.subheader("📋 전체 순위 목록")

# 표에 보여줄 컬럼 선택 및 이름 변경
display_df = df[["rank", "rankIntenDisplay", "displayMovieNm", "openDt", "audiCnt", "audiAcc", "scrnCnt"]].copy()
display_df.columns = ["순위", "순위변동", "영화명", "개봉일", "관객수", "누적관객", "스크린수"]

# 천 단위 쉼표 표기 및 정렬 서식 지정
formatted_df = display_df.style.format({
    "순위": "{:.0f}",
    "관객수": "{:,.0f}",
    "누적관객": "{:,.0f}",
    "스크린수": "{:,.0f}"
})

st.dataframe(formatted_df, use_container_width=True, hide_index=True)
