from typing import List, Optional, TypedDict

import httpx
from selectolax.parser import HTMLParser, Node


class RepoData(TypedDict):
    name: str  # 仓库名 (如: exo-explore / exo)
    url: str  # 相对链接 (如: /exo-explore/exo)
    description: str  # 描述
    language: str  # 编程语言 (可能为空)
    total_stars: str  # 总 Star 数 (保留原始字符串如 "38,582")
    forks: str  # Fork 数
    period_stars: str  # 本周/本日 Star 数 (如 "4,624 stars this week")
    built_by: List[str]  # 贡献者头像链接或用户名


URL = "https://github.com/trending?since=weekly"


def parse_repo_element(node: Node) -> Optional[RepoData]:
    """
    解析单个 <article class="Box-row"> 节点。
    如果关键信息（如标题）缺失，返回 None 以便跳过。
    """

    # 1. 安全获取标题节点
    title_tag = node.css_first("h2 a")

    # [修复 Error 1 & 2] 如果找不到标题，说明这可能不是一个正常的仓库行，直接跳过
    if title_tag is None:
        return None

    # 安全获取属性和文本
    # .text(strip=True) 即使对 None 调用也会报错，但上面已经 guard 了
    name_raw = title_tag.text(strip=True)
    name = "".join(name_raw.split())

    # 获取 href，如果为 None 则给个空字符串
    url_part = title_tag.attributes.get("href") or ""
    url = f"https://github.com{url_part}"

    # 2. 提取描述 (安全处理)
    desc_tag = node.css_first("p.col-9")
    description = desc_tag.text(strip=True) if desc_tag else ""

    # 3. 提取编程语言
    lang_tag = node.css_first("span[itemprop='programmingLanguage']")
    language = lang_tag.text(strip=True) if lang_tag else "Unknown"

    # 4. 提取统计数据
    star_tag = node.css_first("a[href$='/stargazers']")
    total_stars = star_tag.text(strip=True) if star_tag else "0"

    fork_tag = node.css_first("a[href$='/forks']")
    forks = fork_tag.text(strip=True) if fork_tag else "0"

    period_tag = node.css_first("span.float-sm-right")
    period_stars = period_tag.text(strip=True) if period_tag else "0 stars"

    # 5. [修复 Error 3] 提取贡献者并解决类型报错
    built_by_imgs = node.css("span.d-inline-block img.avatar")

    built_by: List[str] = []
    for img in built_by_imgs:
        src = img.attributes.get("src")
        # 显式判断：只有当 src 是字符串且不为空时才加入
        if src and isinstance(src, str):
            built_by.append(src)

    return {
        "name": name,
        "url": url,
        "description": description,
        "language": language,
        "total_stars": total_stars,
        "forks": forks,
        "period_stars": period_stars,
        "built_by": built_by,
    }


def crawler():
    """
    爬取 https://github.com/trending?since=weekly 每周热点趋势
    之后生成list相关数据给后续的节点使用
    """

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        resp = httpx.get(URL, headers=headers)
        html = HTMLParser(resp.text)
        articles = html.css("article.Box-row")
        results: List[RepoData] = []

        for article in articles:
            data = parse_repo_element(article)
            if data:
                results.append(data)

        return results
    except Exception as e:
        print(f"获取趋势数据失败: {e}")
        return []
