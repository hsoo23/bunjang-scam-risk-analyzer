import re
import time
from urllib.parse import quote
from statistics import median

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager


def clean_price(price_text):
    numbers = re.sub(r"[^0-9]", "", price_text)

    if numbers == "":
        return None

    return int(numbers)


def make_search_keyword(title):
    remove_words = [
        "급처", "판매", "팝니다", "삽니다", "교환", "단품",
        "풀박스", "새상품", "미개봉", "거의새것", "사용감",
        "정품", "택포", "무료배송", "네고", "가능", "불가",
        "오늘만", "쿨거", "직거래", "택배", "박스", "구성품",
        "A급", "S급", "상태좋음", "상태 좋음"
    ]

    keyword = title

    for word in remove_words:
        keyword = keyword.replace(word, " ")

    keyword = re.sub(r"[^가-힣a-zA-Z0-9\s]", " ", keyword)
    keyword = re.sub(r"\s+", " ", keyword).strip()

    words = keyword.split()

    if len(words) > 5:
        words = words[:5]

    return " ".join(words)


def crawl_market_prices(keyword, current_price=None, max_count=20):
    encoded_keyword = quote(keyword)
    search_url = f"https://m.bunjang.co.kr/search/products?q={encoded_keyword}"

    chrome_options = Options()
    chrome_options.add_argument("--start-maximized")

    driver = None
    prices = []

    try:
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=chrome_options
        )

        driver.get(search_url)
        time.sleep(5)

        try:
            page_text = driver.find_element(By.TAG_NAME, "body").text
        except NoSuchElementException:
            return []

        lines = page_text.split("\n")
        lines = [line.strip() for line in lines if line.strip()]

        removed_current_price = False

        for line in lines:
            if "원" in line:
                price = clean_price(line)

                if price is not None and price >= 1000:
                    # 현재 분석 중인 판매글 가격은 한 번만 제외
                    if (
                        current_price is not None
                        and price == current_price
                        and not removed_current_price
                    ):
                        removed_current_price = True
                        continue

                    prices.append(price)

                if len(prices) >= max_count:
                    break

        return prices

    except WebDriverException:
        return []

    except Exception:
        return []

    finally:
        if driver is not None:
            driver.quit()


def remove_price_outliers(prices):
    if len(prices) < 3:
        return prices

    prices = sorted(prices)
    mid = median(prices)

    filtered = []

    for price in prices:
        if mid * 0.4 <= price <= mid * 2.5:
            filtered.append(price)

    return filtered


def estimate_market_price(prices):
    if not prices:
        return None

    filtered_prices = remove_price_outliers(prices)

    if not filtered_prices:
        return None

    return int(median(filtered_prices))


def analyze_price_risk(selling_price, market_price):
    if market_price is None:
        return 0, ["시세 정보를 충분히 수집하지 못해 가격 분석을 생략했습니다."]

    ratio = selling_price / market_price

    score = 0
    reasons = []

    if ratio <= 0.3:
        score += 35
        reasons.append(f"판매가가 시세의 {ratio * 100:.1f}% 수준으로 매우 낮습니다. (+35점)")
    elif ratio <= 0.5:
        score += 25
        reasons.append(f"판매가가 시세의 {ratio * 100:.1f}% 수준으로 낮습니다. (+25점)")
    elif ratio <= 0.7:
        score += 10
        reasons.append(f"판매가가 시세의 {ratio * 100:.1f}% 수준으로 다소 낮습니다. (+10점)")
    elif ratio >= 1.5:
        score -= 5
        reasons.append(f"판매가가 시세보다 높은 편이라 저가 사기 위험은 낮게 판단했습니다. (-5점)")
    else:
        reasons.append(f"판매가가 시세의 {ratio * 100:.1f}% 수준으로 크게 의심되지는 않습니다.")

    return score, reasons


def get_market_analysis(title, selling_price):
    try:
        keyword = make_search_keyword(title)

        if keyword == "":
            return {
                "success": False,
                "error": "검색 키워드를 생성하지 못했습니다.",
                "keyword": "",
                "prices": [],
                "filtered_prices": [],
                "market_price": None,
                "market_confidence": "실패",
                "confidence_reasons": ["검색 키워드를 생성하지 못했습니다."],
                "price_score": 0,
                "original_price_score": 0,
                "price_reasons": ["검색 키워드를 생성하지 못해 시세 분석을 생략했습니다."]
            }

        prices = crawl_market_prices(
            keyword=keyword,
            current_price=selling_price,
            max_count=20
        )

        filtered_prices = remove_price_outliers(prices)
        market_price = estimate_market_price(prices)

        market_confidence, confidence_reasons = evaluate_market_confidence(
            keyword=keyword,
            prices=prices,
            filtered_prices=filtered_prices
        )

        price_score, price_reasons = analyze_price_risk(
            selling_price=selling_price,
            market_price=market_price
        )

        adjusted_price_score = adjust_price_score_by_confidence(
            price_score=price_score,
            confidence=market_confidence
        )

        if adjusted_price_score != price_score:
            price_reasons.append(
                f"시세 신뢰도가 '{market_confidence}'이므로 가격 위험 점수를 {price_score}점에서 {adjusted_price_score}점으로 조정했습니다."
            )

        price_reasons.extend(confidence_reasons)

        if not prices:
            return {
                "success": False,
                "error": "검색 결과에서 가격 정보를 수집하지 못했습니다.",
                "keyword": keyword,
                "prices": [],
                "filtered_prices": [],
                "market_price": None,
                "market_confidence": "실패",
                "confidence_reasons": ["검색 결과에서 가격 정보를 수집하지 못했습니다."],
                "price_score": 0,
                "original_price_score": 0,
                "price_reasons": ["검색 결과에서 가격 정보를 수집하지 못해 가격 분석을 생략했습니다."]
            }

        return {
            "success": True,
            "error": None,
            "keyword": keyword,
            "prices": prices,
            "filtered_prices": filtered_prices,
            "market_price": market_price,
            "market_confidence": market_confidence,
            "confidence_reasons": confidence_reasons,
            "price_score": adjusted_price_score,
            "original_price_score": price_score,
            "price_reasons": price_reasons
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"시세 분석 중 오류가 발생했습니다: {e}",
            "keyword": "",
            "prices": [],
            "filtered_prices": [],
            "market_price": None,
            "market_confidence": "실패",
            "confidence_reasons": ["시세 분석 중 오류가 발생했습니다."],
            "price_score": 0,
            "original_price_score": 0,
            "price_reasons": ["시세 분석 중 오류가 발생하여 가격 분석을 생략했습니다."]
        }
    

def evaluate_market_confidence(keyword, prices, filtered_prices):
    """
    수집된 가격 데이터의 개수와 분포를 기준으로 시세 신뢰도를 평가하는 함수.
    특정 상품군 단어를 직접 나열하지 않고, 실제 가격 데이터의 안정성을 기준으로 판단한다.
    """

    reasons = []
    confidence = "높음"

    # 1. 검색 키워드 자체가 너무 짧은 경우
    words = keyword.split()

    if len(words) <= 1:
        confidence = "낮음"
        reasons.append("검색 키워드가 너무 짧아 다양한 상품이 섞일 가능성이 있습니다.")

    # 2. 가격 데이터가 없는 경우
    if len(prices) == 0:
        return "실패", ["검색 결과에서 가격 정보를 수집하지 못했습니다."]

    # 3. 수집된 가격 개수가 너무 적은 경우
    if len(prices) < 3:
        confidence = "매우 낮음"
        reasons.append("수집된 가격이 3개 미만이라 시세로 보기 어렵습니다.")

    elif len(prices) < 5:
        confidence = "낮음"
        reasons.append("수집된 가격이 5개 미만이라 시세 신뢰도가 낮습니다.")

    # 4. 이상치 제거 후 가격이 부족한 경우
    if len(filtered_prices) == 0:
        return "실패", ["이상치 제거 후 남은 가격이 없어 시세 계산이 어렵습니다."]

    if len(filtered_prices) < 3:
        confidence = "매우 낮음"
        reasons.append("이상치 제거 후 남은 가격이 3개 미만입니다.")

    elif len(filtered_prices) < 5:
        if confidence == "높음":
            confidence = "낮음"
        reasons.append("이상치 제거 후 남은 가격이 5개 미만이라 시세 신뢰도가 낮습니다.")

    # 5. 가격 분포가 지나치게 넓은 경우
    min_price = min(filtered_prices)
    max_price = max(filtered_prices)

    if min_price > 0:
        price_spread_ratio = max_price / min_price
    else:
        price_spread_ratio = float("inf")

    if price_spread_ratio >= 4:
        confidence = "낮음"
        reasons.append(
            f"수집된 가격의 최댓값이 최솟값의 {price_spread_ratio:.1f}배로 차이가 커서 동일 상품 시세로 보기 어렵습니다."
        )

    elif price_spread_ratio >= 2.5:
        if confidence == "높음":
            confidence = "보통"
        reasons.append(
            f"수집된 가격의 범위가 다소 넓어 시세 신뢰도가 완전히 높지는 않습니다."
        )

    return confidence, reasons

def adjust_price_score_by_confidence(price_score, confidence):
    """
    시세 신뢰도에 따라 가격 위험 점수 반영 비율을 조정하는 함수
    """

    if confidence == "높음":
        return price_score

    elif confidence == "보통":
        return int(price_score * 0.8)

    elif confidence == "낮음":
        return int(price_score * 0.5)

    elif confidence == "매우 낮음":
        return int(price_score * 0.3)

    elif confidence == "실패":
        return 0

    return price_score

