import re
import time

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager

from market_price import get_market_analysis


# ================================
# 1. 위험 키워드 / 안전 키워드
# ================================

risk_keywords = {
    "급처": 10,
    "선입금": 25,
    "계좌이체": 15,
    "직거래 불가": 20,
    "안전거래 불가": 25,
    "안전거래 안함": 25,
    "안전거래 안됨": 25,
    "인증 불가": 15,
    "카톡": 10,
    "오픈채팅": 10,
    "오늘만": 10,
    "대리구매": 15,
    "대신 구매": 15
}

safe_keywords = {
    "직거래": -10,
    "인증 가능": -10,
    "영수증": -10,
    "실물 확인": -10,
    "거래내역": -10,
    "후기": -5
}


# ================================
# 2. 기본 전처리 함수
# ================================

def clean_text(text):
    text = re.sub(r"[^가-힣a-zA-Z0-9\s]", " ", text) #특문 제거
    text = re.sub(r"\s+", " ", text) #공백 하나로
    return text.strip() #앞뒤 공백 제거


#숫자 또는 쉼표가 포함된 숫자 + 선택적 공백 + 원
def clean_price(price_text):
    match = re.search(r"(\d{1,3}(,\d{3})+|\d+)\s*원", price_text)

    if match is None:
        return None

    price_text = match.group(1)
    price_text = price_text.replace(",", "")

    return int(price_text)


# ================================
# 3. 번개장터 링크에서 정보 추출
# ================================

#Selenium으로 입력받은 링크 접속 -> 데이터 추출
def extract_bunjang_post_info(url):
    chrome_options = Options()
    chrome_options.add_argument("--start-maximized")

    driver = None

    try:
        #크롬 브라우저 자동으로 열고 -> 링크 접속
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=chrome_options
        )

        driver.get(url)
        time.sleep(5)

        try:
            page_text = driver.find_element(By.TAG_NAME, "body").text
        except NoSuchElementException:
            return {
                "success": False,
                "error": "페이지 본문을 찾지 못했습니다.",
                "title": None,
                "price": None,
                "content": "",
                "has_image": "없음"
            }

        #페이지 전체 텍스트 -> 줄 단위 리스트로, 빈 줄 제거
        lines = page_text.split("\n")
        lines = [line.strip() for line in lines if line.strip()]

        if not lines:
            return {
                "success": False,
                "error": "페이지 텍스트를 불러오지 못했습니다.",
                "title": None,
                "price": None,
                "content": "",
                "has_image": "없음"
            }

        title = None
        price = None
        content = ""
        has_image = "없음"

        # 가격 추출
        price_index = None

        for i, line in enumerate(lines):
            possible_price = clean_price(line)

            if possible_price is not None and possible_price >= 1000:
                price = possible_price
                price_index = i
                break

        # 제목 찾기: 가격 바로 위 줄
        if price_index is not None and price_index > 0:
            title = lines[price_index - 1]

        # 이미지 여부 추정
        for i in range(len(lines) - 2):
            if lines[i].isdigit() and lines[i + 1] == "/" and lines[i + 2].isdigit():
                has_image = "있음"
                break

        # 본문 추출
        start_index = None
        end_index = None

        for i, line in enumerate(lines):
            if line == "수량":
                start_index = i + 2
                break

        if start_index is not None:
            for j in range(start_index, len(lines)):
                if lines[j] in ["더보기", "배송비", "직거래 희망 장소", "구매하기"]:
                    end_index = j
                    break

            if end_index is not None:
                content_lines = lines[start_index:end_index]
            else:
                content_lines = lines[start_index:start_index + 10]

            content = " ".join(content_lines)

        # 필수 정보 검증
        if title is None:
            return {
                "success": False,
                "error": "판매글 제목을 추출하지 못했습니다.",
                "title": None,
                "price": price,
                "content": content,
                "has_image": has_image
            }

        if price is None:
            return {
                "success": False,
                "error": "판매 가격을 추출하지 못했습니다.",
                "title": title,
                "price": None,
                "content": content,
                "has_image": has_image
            }

        if content == "":
            content = "본문 설명을 추출하지 못했습니다."

        return {
            "success": True,
            "error": None,
            "title": title,
            "price": price,
            "content": content,
            "has_image": has_image
        }

    except WebDriverException as e:
        return {
            "success": False,
            "error": f"Selenium 실행 중 오류가 발생했습니다: {e}",
            "title": None,
            "price": None,
            "content": "",
            "has_image": "없음"
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"알 수 없는 오류가 발생했습니다: {e}",
            "title": None,
            "price": None,
            "content": "",
            "has_image": "없음"
        }

    finally: #성공이든 실패든 셀레니움 브라우저 무조건 종료
        if driver is not None:
            driver.quit()


# ================================
# 4. 판매글 위험도 분석
# ================================

def analyze_post(title, content, price, has_image):
    score = 0
    reasons = []

    full_text = clean_text(title + " " + content)

    # 1. 위험 키워드 분석
    for keyword, point in risk_keywords.items():
        if keyword in full_text:
            score += point
            reasons.append(f"'{keyword}' 표현이 포함되어 위험 점수가 증가했습니다. (+{point}점)")

    # 2. 안전 키워드 분석
    for keyword, point in safe_keywords.items():
        if keyword in full_text:
            score += point
            reasons.append(f"'{keyword}' 표현이 포함되어 위험 점수가 감소했습니다. ({point}점)")

    # 3. 본문 길이 분석
    if len(content.strip()) < 30:
        score += 10
        reasons.append("본문 설명이 30자 미만으로 너무 짧아 위험 점수가 증가했습니다. (+10점)")

    # 4. 이미지 여부 분석
    if has_image == "없음":
        score += 15
        reasons.append("상품 이미지가 없어 위험 점수가 증가했습니다. (+15점)")

    # 음수 점수 허용
    # score = max(0, min(score, 100))  ← 이 줄은 사용하지 않음

    # 위험 등급 분류
    grade = classify_grade(score)

    return score, grade, reasons

def classify_grade(score):
    if score <= -30:
        return "신뢰도 높음"
    elif score <= 30:
        return "낮음"
    elif score <= 60:
        return "주의"
    else:
        return "위험"

# ================================
# 5. 결과 출력 함수
# ================================

def print_grade(grade):
    icons = {
        "위험":       "🚨",
        "주의":       "⚠️",
        "낮음":       "🟢",
        "신뢰도 높음": "✅",
    }
    icon = icons.get(grade, "")
    print(f"위험 등급: {icon} {grade}")


def print_summary(grade):
    messages = {
        "위험":       "🚨 이 거래는 사기 가능성이 높습니다. 거래를 피하는 것을 권장합니다.",
        "주의":       "⚠️  주의가 필요합니다. 직거래나 안전결제를 요구하세요.",
        "낮음":       "🟢 비교적 안전한 거래로 보입니다. 그래도 안전결제를 이용하세요.",
        "신뢰도 높음": "✅ 신뢰도가 높은 거래로 판단됩니다.",
    }
    print("\n" + messages.get(grade, ""))


# ================================
# 6. 메인 실행 함수
# ================================

def main():
    print("====================================")
    print(" 번개장터 링크 기반 사기 위험도 분석기")
    print("====================================")

    url = input("번개장터 판매글 링크를 입력하세요: ")

    print("\n판매글 정보를 가져오는 중입니다...")

    post_info = extract_bunjang_post_info(url)

    if not post_info["success"]:
        print("\n판매글 정보를 자동으로 가져오지 못했습니다.")
        print("오류 내용:", post_info["error"])
        print("페이지 구조가 바뀌었거나, 링크가 잘못되었거나, 로딩이 실패했을 수 있습니다.")
        print("프로그램을 종료합니다.")
        return

    title = post_info["title"]
    price = post_info["price"]
    content = post_info["content"]
    has_image = post_info["has_image"]

    print("\n===== 추출된 판매글 정보 =====")
    print("제목:", title)
    print("가격:", f"{price:,}원")
    print("본문:", content)
    print("이미지 여부:", has_image)

    text_score, text_grade, text_reasons = analyze_post(
    title=title,
    content=content,
    price=price,
    has_image=has_image
    )

    print("\n시세 정보를 수집하는 중입니다...")

    market_result = get_market_analysis(
        title=title,
        selling_price=price
    )

    if not market_result["success"]:
        print("\n시세 분석을 완료하지 못했습니다.")
        print("사유:", market_result["error"])
        print("가격 기반 위험 점수는 0점으로 처리합니다.")

    print("\n===== 시세 분석 결과 =====")
    print("검색 키워드:", market_result["keyword"])
    print("시세 신뢰도:", market_result["market_confidence"])
    print("수집된 가격 개수:", len(market_result["prices"]))
    print("이상치 제거 후 가격 개수:", len(market_result["filtered_prices"]))
    print(" ")
    print("수집된 가격 목록:", [f"{p:,}원" for p in market_result["prices"]])
    print(" ")
    print("이상치 제거 후 가격 목록:", [f"{p:,}원" for p in market_result["filtered_prices"]])

    if market_result["confidence_reasons"]:
        print("\n시세 신뢰도 관련 사유:")
        for reason in market_result["confidence_reasons"]:
            print("-", reason)

    if market_result["market_price"] is not None:
        print(f"중앙값 기준 시세: {market_result['market_price']:,}원")
    else:
        print("중앙값 기준 시세: 계산 실패")

    price_score = market_result["price_score"]
    price_reasons = market_result["price_reasons"]

    final_score = text_score + price_score
    grade = classify_grade(final_score)
    reasons = text_reasons + price_reasons

    print("\n===== 사기 위험도 분석 결과 =====")
    print(f"텍스트 기반 위험 점수: {text_score}점")
    print(f"가격 기반 위험 점수: {price_score}점")
    print(f"종합 위험 지수: {final_score}점")
    print_grade(grade)

    print("\n의심 사유:")
    if reasons:
        for reason in reasons:
            print("-", reason)
    else:
        print("- 특별한 위험 요소가 발견되지 않았습니다.")

    print_summary(grade)


if __name__ == "__main__":
    main()