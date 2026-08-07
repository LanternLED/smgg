# cogs/kitchen.py
import discord
from discord.ext import commands
import random
import asyncio
import re
import json
import os
from datetime import date

# utils.py에서 공통 함수 불러오기
from utils import async_check_level, async_save_scores, apply_game_reward

INGREDIENTS = ["김치", "참치", "두부", "대패", "대파"]

# 25종 진상 손님 템플릿 전문
order_templates = [
    {
        "order": "내 피에는 **{food}**가 흐른다.", "success": "**{food}**가 끓어오른다.",
        "away": "(손님이 잠시 자리를 비웠다...)",
        "return_normal": "(손님이 다시 돌아와 **{food}**를 기다린다.)",
        "return_add": "(손님이 다시 돌아와, **{food2}**를 추가로 주문했다...!)",
        "wait_next": "(손님이 음식을 받고, **{food_remain}**을(를) 기다리고 있다...)",
        "fail": "(손님이 당황하며 자신의 주문이 **{food}**와(과) **{food2}**였다고 말한다)",
        "wrong_order": "손님이 '{name}'은(는) 시키지 않았다며 화를 냈다.",
        "timeout_partial": "시간이 너무 늦어 첫 번째 음식 값만 치르고 가겠습니다. 실망스럽네요.",
        "timeout_failure": "기다리다 지쳐 떠나갔다..."
    },
    {
        "order": "세계 멸망까지 단 하루, **{food}**, 황홀.", "success": "우리 모두가 안식하는 그날까지.",
        "away": "(손님이 잠시 자리를 비웠다...)",
        "return_normal": "(손님이 다시 돌아와 **{food}**를 기다린다.)",
        "return_add": "(손님이 다시 돌아와, **{food2}**를 추가로 주문했다...!)",
        "wait_next": "(손님이 음식을 받고, **{food_remain}**을(를) 기다리고 있다...)",
        "fail": "(손님이 당황하며 자신의 주문이 **{food}**와(과) **{food2}**였다고 말한다)",
        "wrong_order": "손님이 '{name}'은(는) 시키지 않았다며 화를 냈다.",
        "timeout_partial": "시간이 너무 늦어 첫 번째 음식 값만 치르고 가겠습니다. 실망스럽네요.",
        "timeout_failure": "기다리다 지쳐 떠나갔다..."
    },
    {
        "order": "초전도 **{food}**가 여기서 개발된 것 맞죠?", "success": "이것은 요리계의 혁명인!",
        "away": "(손님이 잠시 자리를 비웠다...)",
        "return_normal": "(손님이 다시 돌아와 **{food}**를 기다린다.)",
        "return_add": "(손님이 다시 돌아와, **{food2}**를 추가로 주문했다...!)",
        "wait_next": "(손님이 음식을 받고, **{food_remain}**을(를) 기다리고 있다...)",
        "fail": "(손님이 당황하며 자신의 주문이 **{food}**와(과) **{food2}**였다고 말한다)",
        "wrong_order": "손님이 '{name}'은(는) 시키지 않았다며 화를 냈다.",
        "timeout_partial": "시간이 너무 늦어 첫 번째 음식 값만 치르고 가겠습니다. 실망스럽네요.",
        "timeout_failure": "기다리다 지쳐 떠나갔다..."
    },
    {
        "order": "세상을 구하기 위해서는 **{food}**가 필요해!", "success": "설명할 시간이 없어, 어서 타!",
        "away": "(손님이 잠시 자리를 비웠다...)",
        "return_normal": "(손님이 다시 돌아와 **{food}**를 기다린다.)",
        "return_add": "(손님이 다시 돌아와, **{food2}**를 추가로 주문했다...!)",
        "wait_next": "(손님이 음식을 받고, **{food_remain}**을(를) 기다리고 있다...)",
        "fail": "(손님이 당황하며 자신의 주문이 **{food}**와(과) **{food2}**였다고 말한다)",
        "wrong_order": "손님이 '{name}'은(는) 시키지 않았다며 화를 냈다.",
        "timeout_partial": "시간이 너무 늦어 첫 번째 음식 값만 치르고 가겠습니다. 실망스럽네요.",
        "timeout_failure": "기다리다 지쳐 떠나갔다..."
    },
    {
        "order": "오늘은 100년 전통 **{food}** 맛집을 찾아왔습니다!", "success": "구독, 좋아요, 알림설정! 부탁드립니다~",
        "away": "(손님이 잠시 자리를 비웠다...)",
        "return_normal": "(손님이 다시 돌아와 **{food}**를 기다린다.)",
        "return_add": "(손님이 다시 돌아와, **{food2}**를 추가로 주문했다...!)",
        "wait_next": "(손님이 음식을 받고, **{food_remain}**을(를) 기다리고 있다...)",
        "fail": "(손님이 당황하며 자신의 주문이 **{food}**와(과) **{food2}**였다고 말한다)",
        "wrong_order": "손님이 '{name}'은(는) 시키지 않았다며 화를 냈다.",
        "timeout_partial": "시간이 너무 늦어 첫 번째 음식 값만 치르고 가겠습니다. 실망스럽네요.",
        "timeout_failure": "기다리다 지쳐 떠나갔다..."
    },
    {
        "order": "넌 아직 **{food}** 할 준비가 안됐다.", "success": "**{food}**는 나의 것이다!",
        "away": "(손님이 잠시 자리를 비웠다...)",
        "return_normal": "(손님이 다시 돌아와 **{food}**를 기다린다.)",
        "return_add": "(손님이 다시 돌아와, **{food2}**를 추가로 주문했다...!)",
        "wait_next": "(손님이 음식을 받고, **{food_remain}**을(를) 기다리고 있다...)",
        "fail": "(손님이 당황하며 자신의 주문이 **{food}**와(과) **{food2}**였다고 말한다)",
        "wrong_order": "손님이 '{name}'은(는) 시키지 않았다며 화를 냈다.",
        "timeout_partial": "시간이 너무 늦어 첫 번째 음식 값만 치르고 가겠습니다. 실망스럽네요.",
        "timeout_failure": "기다리다 지쳐 떠나갔다..."
    },
    {
        "order": "**{food}**! **{food}**! **{food}**!", "success": "그분이 오신다...!",
        "away": "(손님이 잠시 자리를 비웠다...)",
        "return_normal": "(손님이 다시 돌아와 **{food}**를 기다린다.)",
        "return_add": "(손님이 다시 돌아와, **{food2}**를 추가로 주문했다...!)",
        "wait_next": "(손님이 음식을 받고, **{food_remain}**을(를) 기다리고 있다...)",
        "fail": "(손님이 당황하며 자신의 주문이 **{food}**와(과) **{food2}**였다고 말한다)",
        "wrong_order": "손님이 '{name}'은(는) 시키지 않았다며 화를 냈다.",
        "timeout_partial": "시간이 너무 늦어 첫 번째 음식 값만 치르고 가겠습니다. 실망스럽네요.",
        "timeout_failure": "기다리다 지쳐 떠나갔다..."
    },
    {
        "order": "**{food}**를 믿으면 극락왕생합니다. **{food}**를 믿으세요.", "success": "**{food}**천국! 불신지옥!",
        "away": "(손님이 잠시 자리를 비웠다...)",
        "return_normal": "(손님이 다시 돌아와 **{food}**를 기다린다.)",
        "return_add": "(손님이 다시 돌아와, **{food2}**를 추가로 주문했다...!)",
        "wait_next": "(손님이 음식을 받고, **{food_remain}**을(를) 기다리고 있다...)",
        "fail": "(손님이 당황하며 자신의 주문이 **{food}**와(과) **{food2}**였다고 말한다)",
        "wrong_order": "손님이 '{name}'은(는) 시키지 않았다며 화를 냈다.",
        "timeout_partial": "시간이 너무 늦어 첫 번째 음식 값만 치르고 가겠습니다. 실망스럽네요.",
        "timeout_failure": "기다리다 지쳐 떠나갔다..."
    },
    {
        "order": "**{food}**가 이렇게까지 유행할 일인가...?", "success": "허니버터칩, 두쫀쿠, **{food}**, 레츠 고!",
        "away": "(손님이 잠시 자리를 비웠다...)",
        "return_normal": "(손님이 다시 돌아와 **{food}**를 기다린다.)",
        "return_add": "(손님이 다시 돌아와, **{food2}**를 추가로 주문했다...!)",
        "wait_next": "(손님이 음식을 받고, **{food_remain}**을(를) 기다리고 있다...)",
        "fail": "(손님이 당황하며 자신의 주문이 **{food}**와(과) **{food2}**였다고 말한다)",
        "wrong_order": "손님이 '{name}'은(는) 시키지 않았다며 화를 냈다.",
        "timeout_partial": "시간이 너무 늦어 첫 번째 음식 값만 치르고 가겠습니다. 실망스럽네요.",
        "timeout_failure": "기다리다 지쳐 떠나갔다..."
    },
    {
        "order": "**{food}**를 파는 식당 수십 곳을 전전했지만, 이 집이 단연 최고다!", "success": "사장님, 많이 파시고 오래오래 장사하세요!",
        "away": "(손님이 잠시 자리를 비웠다...)",
        "return_normal": "(손님이 다시 돌아와 **{food}**를 기다린다.)",
        "return_add": "(손님이 다시 돌아와, **{food2}**를 추가로 주문했다...!)",
        "wait_next": "(손님이 음식을 받고, **{food_remain}**을(를) 기다리고 있다...)",
        "fail": "(손님이 당황하며 자신의 주문이 **{food}**와(과) **{food2}**였다고 말한다)",
        "wrong_order": "손님이 '{name}'은(는) 시키지 않았다며 화를 냈다.",
        "timeout_partial": "시간이 너무 늦어 첫 번째 음식 값만 치르고 가겠습니다. 실망스럽네요.",
        "timeout_failure": "기다리다 지쳐 떠나갔다..."
    },
    {
        "order": "**{food}**. 얼마면 돼.", "success": "요즘 **{food}** 구경하기도 어려워졌군.",
        "away": "(손님이 잠시 자리를 비웠다...)",
        "return_normal": "(손님이 다시 돌아와 **{food}**를 기다린다.)",
        "return_add": "(손님이 다시 돌아와, **{food2}**를 추가로 주문했다...!)",
        "wait_next": "(손님이 음식을 받고, **{food_remain}**을(를) 기다리고 있다...)",
        "fail": "(손님이 당황하며 자신의 주문이 **{food}**와(과) **{food2}**였다고 말한다)",
        "wrong_order": "손님이 '{name}'은(는) 시키지 않았다며 화를 냈다.",
        "timeout_partial": "시간이 너무 늦어 첫 번째 음식 값만 치르고 가겠습니다. 실망스럽네요.",
        "timeout_failure": "기다리다 지쳐 떠나갔다..."
    },
    {
        "order": "응급 환자입니다! 빨리 **{food}** 수혈을!", "success": "오해하지 말아주세요! 제가 먹고 힘내서 수술을 들어갈 예정이니까!",
        "away": "(손님이 잠시 자리를 비웠다...)",
        "return_normal": "(손님이 다시 돌아와 **{food}**를 기다린다.)",
        "return_add": "(손님이 다시 돌아와, **{food2}**를 추가로 주문했다...!)",
        "wait_next": "(손님이 음식을 받고, **{food_remain}**을(를) 기다리고 있다...)",
        "fail": "(손님이 당황하며 자신의 주문이 **{food}**와(과) **{food2}**였다고 말한다)",
        "wrong_order": "손님이 '{name}'은(는) 시키지 않았다며 화를 냈다.",
        "timeout_partial": "시간이 너무 늦어 첫 번째 음식 값만 치르고 가겠습니다. 실망스럽네요.",
        "timeout_failure": "기다리다 지쳐 떠나갔다..."
    },
    {
        "order": "내게는 **{food}**밖에 없습니다.", "success": "그것 말고는 아무것도 바라지 않습니다.",
        "away": "(손님이 잠시 자리를 비웠다...)",
        "return_normal": "(손님이 다시 돌아와 **{food}**를 기다린다.)",
        "return_add": "(손님이 다시 돌아와, **{food2}**를 추가로 주문했다...!)",
        "wait_next": "(손님이 음식을 받고, **{food_remain}**을(를) 기다리고 있다...)",
        "fail": "(손님이 당황하며 자신의 주문이 **{food}**와(과) **{food2}**였다고 말한다)",
        "wrong_order": "손님이 '{name}'은(는) 시키지 않았다며 화를 냈다.",
        "timeout_partial": "시간이 너무 늦어 첫 번째 음식 값만 치르고 가겠습니다. 실망스럽네요.",
        "timeout_failure": "기다리다 지쳐 떠나갔다..."
    },
    {
        "order": "이 세상은 **{food}**를 조리하는 자와 **{food}**를 먹는 자로 이루어져 있다.", "success": "나는 먹는 자다.",
        "away": "(손님이 잠시 자리를 비웠다...)",
        "return_normal": "(손님이 다시 돌아와 **{food}**를 기다린다.)",
        "return_add": "(손님이 다시 돌아와, **{food2}**를 추가로 주문했다...!)",
        "wait_next": "(손님이 음식을 받고, **{food_remain}**을(를) 기다리고 있다...)",
        "fail": "(손님이 당황하며 자신의 주문이 **{food}**와(과) **{food2}**였다고 말한다)",
        "wrong_order": "손님이 '{name}'은(는) 시키지 않았다며 화를 냈다.",
        "timeout_partial": "시간이 너무 늦어 첫 번째 음식 값만 치르고 가겠습니다. 실망스럽네요.",
        "timeout_failure": "기다리다 지쳐 떠나갔다..."
    },
    {
        "order": "전 항상 **{food}**를 먹지 못했던 것이 한이었어요.", "success": "꿈☆은 이루어진다...!",
        "away": "(손님이 잠시 자리를 비웠다...)",
        "return_normal": "(손님이 다시 돌아와 **{food}**를 기다린다.)",
        "return_add": "(손님이 다시 돌아와, **{food2}**를 추가로 주문했다...!)",
        "wait_next": "(손님이 음식을 받고, **{food_remain}**을(를) 기다리고 있다...)",
        "fail": "(손님이 당황하며 자신의 주문이 **{food}**와(과) **{food2}**였다고 말한다)",
        "wrong_order": "손님이 '{name}'은(는) 시키지 않았다며 화를 냈다.",
        "timeout_partial": "시간이 너무 늦어 첫 번째 음식 값만 치르고 가겠습니다. 실망스럽네요.",
        "timeout_failure": "기다리다 지쳐 떠나갔다..."
    },
    {
        "order": "여봐라, 짐에게 **{food}**를 가져와라!", "success": "어명이다!",
        "away": "(손님이 잠시 자리를 비웠다...)",
        "return_normal": "(손님이 다시 돌아와 **{food}**를 기다린다.)",
        "return_add": "(손님이 다시 돌아와, **{food2}**를 추가로 주문했다...!)",
        "wait_next": "(손님이 음식을 받고, **{food_remain}**을(를) 기다리고 있다...)",
        "fail": "(손님이 당황하며 자신의 주문이 **{food}**와(과) **{food2}**였다고 말한다)",
        "wrong_order": "손님이 '{name}'은(는) 시키지 않았다며 화를 냈다.",
        "timeout_partial": "시간이 너무 늦어 첫 번째 음식 값만 치르고 가겠습니다. 실망스럽네요.",
        "timeout_failure": "기다리다 지쳐 떠나갔다..."
    },
    {
        "order": "**{food}**.", "success": "**{food}**",
        "away": "(손님이 잠시 자리를 비웠다...)",
        "return_normal": "(손님이 다시 돌아와 **{food}**를 기다린다.)",
        "return_add": "(손님이 다시 돌아와, **{food2}**를 추가로 주문했다...!)",
        "wait_next": "(손님이 음식을 받고, **{food_remain}**을(를) 기다리고 있다...)",
        "fail": "(손님이 당황하며 자신의 주문이 **{food}**와(과) **{food2}**였다고 말한다)",
        "wrong_order": "손님이 '{name}'은(는) 시키지 않았다며 화를 냈다.",
        "timeout_partial": "시간이 너무 늦어 첫 번째 음식 값만 치르고 가겠습니다. 실망스럽네요.",
        "timeout_failure": "기다리다 지쳐 떠나갔다..."
    },
    {
        "order": "이 세계는 미쳤어... 왜 **{food}** 같은 음식이 존재하는 거야...?", "success": "주인장도 몸 조심해, 요즘 이상한 신흥 종교가 번지고 있는 모양이야.",
        "away": "(손님이 잠시 자리를 비웠다...)",
        "return_normal": "(손님이 다시 돌아와 **{food}**를 기다린다.)",
        "return_add": "(손님이 다시 돌아와, **{food2}**를 추가로 주문했다...!)",
        "wait_next": "(손님이 음식을 받고, **{food_remain}**을(를) 기다리고 있다...)",
        "fail": "(손님이 당황하며 자신의 주문이 **{food}**와(과) **{food2}**였다고 말한다)",
        "wrong_order": "손님이 '{name}'은(는) 시키지 않았다며 화를 냈다.",
        "timeout_partial": "시간이 너무 늦어 첫 번째 음식 값만 치르고 가겠습니다. 실망스럽네요.",
        "timeout_failure": "기다리다 지쳐 떠나갔다..."
    },
    {
        "order": "저는 강도에오. **{food}**를 주세오.", "success": "저는 생계형 강도에오.",
        "away": "(손님이 잠시 자리를 비웠다...)",
        "return_normal": "(손님이 다시 돌아와 **{food}**를 기다린다.)",
        "return_add": "(손님이 다시 돌아와, **{food2}**를 추가로 주문했다...!)",
        "wait_next": "(손님이 음식을 받고, **{food_remain}**을(를) 기다리고 있다...)",
        "fail": "(손님이 당황하며 자신의 주문이 **{food}**와(과) **{food2}**였다고 말한다)",
        "wrong_order": "손님이 '{name}'은(는) 시키지 않았다며 화를 냈다.",
        "timeout_partial": "시간이 너무 늦어 첫 번째 음식 값만 치르고 가겠습니다. 실망스럽네요.",
        "timeout_failure": "기다리다 지쳐 떠나갔다..."
    },
    {
        "order": "당진 맛집 감자네 **{food}**! 망령이 백덤블링을 하고 랜턴이 감탄사를 참지 못하는!", "success": "대파가 날이면 날마다 먹고 재윤이 찾아가는!",
        "away": "(손님이 잠시 자리를 비웠다...)",
        "return_normal": "(손님이 다시 돌아와 **{food}**를 기다린다.)",
        "return_add": "(손님이 다시 돌아와, **{food2}**를 추가로 주문했다...!)",
        "wait_next": "(손님이 음식을 받고, **{food_remain}**을(를) 기다리고 있다...)",
        "fail": "(손님이 당황하며 자신의 주문이 **{food}**와(과) **{food2}**였다고 말한다)",
        "wrong_order": "손님이 '{name}'은(는) 시키지 않았다며 화를 냈다.",
        "timeout_partial": "시간이 너무 늦어 첫 번째 음식 값만 치르고 가겠습니다. 실망스럽네요.",
        "timeout_failure": "기다리다 지쳐 떠나갔다..."
    },
    {
        "order": "군대에서 나온 **{food}**는 참혹하기 이루 말할 데가 없었다.", "success": "그건... 짬밥이었어...",
        "away": "(손님이 잠시 자리를 비웠다...)",
        "return_normal": "(손님이 다시 돌아와 **{food}**를 기다린다.)",
        "return_add": "(손님이 다시 돌아와, **{food2}**를 추가로 주문했다...!)",
        "wait_next": "(손님이 음식을 받고, **{food_remain}**을(를) 기다리고 있다...)",
        "fail": "(손님이 당황하며 자신의 주문이 **{food}**와(과) **{food2}**였다고 말한다)",
        "wrong_order": "손님이 '{name}'은(는) 시키지 않았다며 화를 냈다.",
        "timeout_partial": "시간이 너무 늦어 첫 번째 음식 값만 치르고 가겠습니다. 실망스럽네요.",
        "timeout_failure": "기다리다 지쳐 떠나갔다..."
    },
    {
        "order": "별 하나에 추억과, 별 하나에 사랑과, 별 하나에 아름다운 **{food}** 한마디씩 불러 봅니다.", "success": "**{food}**는 너무나 멀리 있습니다. 별이 아스라이 멀듯이.",
        "away": "(손님이 잠시 자리를 비웠다...)",
        "return_normal": "(손님이 다시 돌아와 **{food}**를 기다린다.)",
        "return_add": "(손님이 다시 돌아와, **{food2}**를 추가로 주문했다...!)",
        "wait_next": "(손님이 음식을 받고, **{food_remain}**을(를) 기다리고 있다...)",
        "fail": "(손님이 당황하며 자신의 주문이 **{food}**와(과) **{food2}**였다고 말한다)",
        "wrong_order": "손님이 '{name}'은(는) 시키지 않았다며 화를 냈다.",
        "timeout_partial": "시간이 너무 늦어 첫 번째 음식 값만 치르고 가겠습니다. 실망스럽네요.",
        "timeout_failure": "기다리다 지쳐 떠나갔다..."
    },
    {
        "order": "제일의**{food}**가무섭다고그러오", "success": "그중에일인의**{food}**가무서운**{food}**라도좋소",
        "away": "(손님이 잠시 자리를 비웠다...)",
        "return_normal": "(손님이 다시 돌아와 **{food}**를 기다린다.)",
        "return_add": "(손님이 다시 돌아와, **{food2}**를 추가로 주문했다...!)",
        "wait_next": "(손님이 음식을 받고, **{food_remain}**을(를) 기다리고 있다...)",
        "fail": "(손님이 당황하며 자신의 주문이 **{food}**와(과) **{food2}**였다고 말한다)",
        "wrong_order": "손님이 '{name}'은(는) 시키지 않았다며 화를 냈다.",
        "timeout_partial": "시간이 너무 늦어 첫 번째 음식 값만 치르고 가겠습니다. 실망스럽네요.",
        "timeout_failure": "기다리다 지쳐 떠나갔다..."
    },
    {
        "order": "**{food}**는 가라.", "success": "그 모오든 **{food}**는 가라.",
        "away": "(손님이 잠시 자리를 비웠다...)",
        "return_normal": "(손님이 다시 돌아와 **{food}**를 기다린다.)",
        "return_add": "(손님이 다시 돌아와, **{food2}**를 추가로 주문했다...!)",
        "wait_next": "(손님이 음식을 받고, **{food_remain}**을(를) 기다리고 있다...)",
        "fail": "(손님이 당황하며 자신의 주문이 **{food}**와(과) **{food2}**였다고 말한다)",
        "wrong_order": "손님이 '{name}'은(는) 시키지 않았다며 화를 냈다.",
        "timeout_partial": "시간이 너무 늦어 첫 번째 음식 값만 치르고 가겠습니다. 실망스럽네요.",
        "timeout_failure": "기다리다 지쳐 떠나갔다..."
    },
    {
        "order": "밤에 홀로 **{food}**를 먹는 것은 외로운 황홀한 심사이어니", "success": "아아, 늬는 산새처럼 날아갔구나!",
        "away": "(손님이 잠시 자리를 비웠다...)",
        "return_normal": "(손님이 다시 돌아와 **{food}**를 기다린다.)",
        "return_add": "(손님이 다시 돌아와, **{food2}**를 추가로 주문했다...!)",
        "wait_next": "(손님이 음식을 받고, **{food_remain}**을(를) 기다리고 있다...)",
        "fail": "(손님이 당황하며 자신의 주문이 **{food}**와(과) **{food2}**였다고 말한다)",
        "wrong_order": "손님이 '{name}'은(는) 시키지 않았다며 화를 냈다.",
        "timeout_partial": "시간이 너무 늦어 첫 번째 음식 값만 치르고 가겠습니다. 실망스럽네요.",
        "timeout_failure": "기다리다 지쳐 떠나갔다..."
    }
]

active_kitchen_games = {}
RANKING_FILE = "weekly_ranking.json"

async def save_and_get_weekly_ranking(user_id: int, user_name: str, score: int) -> int:
    data = {}
    current_week = date.today().isocalendar()
    if os.path.exists(RANKING_FILE):
        with open(RANKING_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            
    if data.get("year") != current_week[0] or data.get("week") != current_week[1]:
        data = {"year": current_week[0], "week": current_week[1], "scores": {}}
        
    uid_str = str(user_id)
    scores = data["scores"]
    
    is_new_best = False
    if uid_str not in scores or score > scores[uid_str]["score"]:
        scores[uid_str] = {"name": user_name, "score": score}
        is_new_best = True
        
    with open(RANKING_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        
    if not is_new_best:
        return -1
        
    sorted_scores = sorted(scores.values(), key=lambda x: x["score"], reverse=True)
    for i, entry in enumerate(sorted_scores):
        if entry["score"] == score and entry["name"] == user_name:
            return i + 1
    return -1

class GameState:
    def __init__(self, user_id: int, user_name: str, channel_id: int) -> None:
        self.user_id = user_id
        self.user_name = user_name
        self.channel_id = channel_id
        self.score: int = 0

        self.pot_items: list[dict] = []
        self.pot_stew: dict | None = None
        self.hand: dict[str, dict] = {}
        self.last_hand_base: str | None = None
        self.fridge: list[dict | None] = [None] * 7

        self.orders: list[dict] = []
        self.current_template: dict | None = None
        self.is_away: bool = False
        self.has_part_timer: bool = False  # 알바생 고용 여부
        self.time_left: int = 0
        self.timer_task: asyncio.Task | None = None

        self.embed_msg: discord.Message | None = None
        self.last_event: str = "게임을 시작했다! 손님의 주문을 기다리자."
        self.lock: asyncio.Lock = asyncio.Lock()

    @property
    def stage(self) -> int:
        return int(max(pow(self.score // 3, 0.5), 1))

    @property
    def max_name_len(self) -> int:
        expansions = (self.stage - 1) // 3
        return 2 + (self.stage - 1) * 2 - (expansions * 4)

    @property
    def time_limit(self) -> int:
        return 30 + self.stage * 1

    def get_features(self) -> dict:
        s = self.stage
        f = {"dim": 0, "away_prob": 0.0, "add_prob": 0.0}
        if s >= 11: f["dim"] = 1
        if s >= 20: f["dim"] = 2
        if s >= 29: f["dim"] = 3
        
        if s >= 8: f["away_prob"] = 0.1
        if s >= 14: f["away_prob"] = 0.2
        if s >= 23: f["away_prob"] = 0.1; f["add_prob"] = 0.1
        if s >= 32: f["away_prob"] = 0.2; f["add_prob"] = 0.2
        return f

    def unlocked(self) -> list[str]:
        s = self.stage
        u = ["김치"]
        if s >= 5: u.append("참치")
        if s >= 17: u.append("두부")
        if s >= 26: u.append("대패")
        if s >= 35: u.append("대파")
        return u

    def generate_single_order(self, target_max_len: int) -> dict:
        u = self.unlocked()
        max_k = len(u)
        target_ing_dim = self.get_features()["dim"]

        memo_item = {}
        def can_make_item(L, max_D, is_trunk):
            if L == 2: return True
            if L < 6: return False
            if not is_trunk and max_D <= 0: return False
            state = (L, max_D, is_trunk)
            if state in memo_item: return memo_item[state]
            next_D = max_D if is_trunk else max_D - 1
            res = any(can_make_stew(L - 4, k, next_D, is_trunk) for k in range(1, max_k + 1))
            memo_item[state] = res
            return res

        memo_stew = {}
        def can_make_stew(sum_L, k, max_D, is_trunk):
            if k == 0: return sum_L == 0
            if sum_L <= 0: return False
            state = (sum_L, k, max_D, is_trunk)
            if state in memo_stew: return memo_stew[state]

            if k == 1:
                res = can_make_item(sum_L, max_D, is_trunk)
            else:
                res = False
                if is_trunk:
                    for L_trunk in range(2, sum_L, 2):
                        if can_make_item(L_trunk, max_D, True):
                            if can_make_stew(sum_L - L_trunk, k - 1, max_D, False):
                                res = True
                                break
                else:
                    for L_branch in range(2, sum_L, 2):
                        if can_make_item(L_branch, max_D, False):
                            if can_make_stew(sum_L - L_branch, k - 1, max_D, False):
                                res = True
                                break
            memo_stew[state] = res
            return res

        valid_lengths = []
        for L in range(2, target_max_len + 1, 2):
            if L == 2:
                valid_lengths.append(2)
                continue
            can_be_stew = any(can_make_stew(L - 2, k, target_ing_dim, True) for k in range(1, max_k + 1))
            can_be_item = (L >= 6) and any(can_make_stew(L - 4, k, target_ing_dim, True) for k in range(1, max_k + 1))
            if can_be_stew or can_be_item:
                valid_lengths.append(L)

        meal_kit = None

        if not valid_lengths:
            order_food = random.choice(u) + "찌개"
            answer_recipe = f"{order_food.replace('찌개', '')}를 끓여서 낸다"
        else:
            max_L = max(valid_lengths)
            weights = [5 if L == max_L else 1 for L in valid_lengths]
            chosen_L = random.choices(valid_lengths, weights=weights, k=1)[0]

            def build_item(L, max_D, is_trunk, all_bases, forced_base=None):
                if L == 2:
                    b = forced_base if forced_base else random.choice(all_bases)
                    return {"name": b, "base": b, "recipe": f"{b}를 넣고 "}
                stew_L = L - 4
                next_D = max_D if is_trunk else max_D - 1
                valid_ks = [k for k in range(1, len(all_bases) + 1) if can_make_stew(stew_L, k, next_D, is_trunk)]
                k = random.choice(valid_ks)
                stew = build_stew(stew_L, k, next_D, is_trunk, all_bases, force_include_base=forced_base)
                b = forced_base if forced_base else random.choice(stew["bases"])
                return {"name": stew["name"] + "찌개" + b, "base": b, "recipe": stew["recipe"] + f"끓이고 {b}를 건져서 "}

            def build_stew(sum_L, k, max_D, is_trunk, all_bases, force_include_base=None):
                pool = [b for b in all_bases if b != force_include_base]
                k_to_sample = k - (1 if force_include_base else 0)
                chosen_bases = random.sample(pool, k_to_sample)
                if force_include_base:
                    chosen_bases.append(force_include_base)
                random.shuffle(chosen_bases)
                items = []
                rem_sum = sum_L
                rem_k = k

                if is_trunk:
                    valid_L_trunks = []
                    if rem_k == 1:
                        valid_L_trunks.append(rem_sum)
                    else:
                        for L_trunk in range(2, rem_sum, 2):
                            if can_make_item(L_trunk, max_D, True) and can_make_stew(rem_sum - L_trunk, rem_k - 1, max_D, False):
                                valid_L_trunks.append(L_trunk)
                    L_trunk = random.choice(valid_L_trunks)
                    trunk_base = chosen_bases[0]
                    items.append(build_item(L_trunk, max_D, True, all_bases, forced_base=trunk_base))
                    rem_sum -= L_trunk
                    rem_k -= 1
                    for i in range(rem_k):
                        if rem_k - i == 1: L_branch = rem_sum
                        else:
                            valid_L_branches = [L1 for L1 in range(2, rem_sum, 2) if can_make_item(L1, max_D, False) and can_make_stew(rem_sum - L1, rem_k - i - 1, max_D, False)]
                            L_branch = random.choice(valid_L_branches)
                        branch_base = chosen_bases[i + 1]
                        items.append(build_item(L_branch, max_D, False, all_bases, forced_base=branch_base))
                        rem_sum -= L_branch
                else:
                    for i in range(rem_k):
                        if rem_k - i == 1: L_branch = rem_sum
                        else:
                            valid_L_branches = [L1 for L1 in range(2, rem_sum, 2) if can_make_item(L1, max_D, False) and can_make_stew(rem_sum - L1, rem_k - i - 1, max_D, False)]
                            L_branch = random.choice(valid_L_branches)
                        branch_base = chosen_bases[i]
                        items.append(build_item(L_branch, max_D, False, all_bases, forced_base=branch_base))
                        rem_sum -= L_branch

                random.shuffle(items)
                recipe_str = ""
                for itm in items:
                    if "건져서" in itm["recipe"]: recipe_str += itm["recipe"]
                for itm in items:
                    if "건져서" in itm["recipe"]: recipe_str += f"그 {itm['base']}를 넣고 "
                    else: recipe_str += itm["recipe"]
                
                # 밀키트 생성을 위해 trunk(첫 번째 줄기) 정보를 함께 반환
                return {
                    "name": "".join(itm["name"] for itm in items), 
                    "bases": [itm["base"] for itm in items], 
                    "recipe": recipe_str,
                    "trunk": items[0] if items else None
                }

            if chosen_L == 2:
                order_food = random.choice(u)
                answer_recipe = f"{order_food}를 낸다"
            else:
                can_stew = any(can_make_stew(chosen_L - 2, k, target_ing_dim, True) for k in range(1, max_k + 1))
                can_item = (chosen_L >= 6) and any(can_make_stew(chosen_L - 4, k, target_ing_dim, True) for k in range(1, max_k + 1))
                is_stew = True
                if can_stew and can_item: is_stew = random.choice([True, False])
                elif can_item: is_stew = False

                if is_stew:
                    stew_L = chosen_L - 2
                    valid_ks = [k for k in range(1, max_k + 1) if can_make_stew(stew_L, k, target_ing_dim, True)]
                    k = random.choice(valid_ks)
                    stew = build_stew(stew_L, k, target_ing_dim, True, u)
                    order_food = stew["name"] + "찌개"
                    answer_recipe = stew["recipe"] + "끓여서 낸다"
                    if stew["trunk"]:
                        meal_kit = {"name": stew["trunk"]["name"], "dim": target_ing_dim, "base": stew["trunk"]["base"]}
                else:
                    stew_L = chosen_L - 4
                    valid_ks = [k for k in range(1, max_k + 1) if can_make_stew(stew_L, k, target_ing_dim, True)]
                    k = random.choice(valid_ks)
                    stew = build_stew(stew_L, k, target_ing_dim, True, u)
                    ext_base = random.choice(stew["bases"])
                    order_food = stew["name"] + "찌개" + ext_base
                    answer_recipe = stew["recipe"] + f"끓이고 {ext_base}를 건져서 낸다"
                    if stew["trunk"]:
                        meal_kit = {"name": stew["trunk"]["name"], "dim": target_ing_dim, "base": stew["trunk"]["base"]}

        return {
            "food": order_food,
            "recipe": answer_recipe,
            "completed": False,
            "dim": target_ing_dim,
            "earned_pts": 0,
            "meal_kit": meal_kit
        }

    def insert_meal_kit(self, meal_kit: dict) -> str:
        if not self.has_part_timer or not meal_kit: 
            return ""
        empty_slots = [i for i, s in enumerate(self.fridge) if s is None]
        if empty_slots:
            idx = random.choice(empty_slots)
            self.fridge[idx] = {"name": meal_kit["name"], "dim": meal_kit["dim"], "base": meal_kit["base"]}
            return f"\n🧑‍🍳 알바생이 빈 공간에 [**{meal_kit['name']}**] 밀키트를 준비했습니다!"
        return ""

    def new_order(self, reset_time: bool = True) -> None:
        self.current_template = random.choice(order_templates)
        
        first_order = self.generate_single_order(self.max_name_len)
        first_order["name"] = self.current_template["order"].format(food=first_order["food"])
        first_order["success"] = self.current_template["success"].format(food=first_order["food"])
        
        self.orders = [first_order]
        self.is_away = False

        if reset_time:
            if self.score == 0:
                self.time_left = self.time_limit
            else:
                recovery = int(self.time_limit * 0.5)
                self.time_left = min(self.time_limit, self.time_left + recovery)

        # 알바생 밀키트 생성 로직
        mk_msg = self.insert_meal_kit(first_order.get("meal_kit"))
        if mk_msg:
            self.last_event += mk_msg

    def score_for(self, name: str, dim: int) -> int:
        return max (int(len(name) * (dim + 1) * (1 + self.stage * 0.05)), 5)

    def fridge_text(self) -> str:
        lines = []
        for i, slot in enumerate(self.fridge):
            lines.append(f"{i + 1}) {slot['name'] if slot else ''}")
        return "\n".join(lines)

    def make_embed(self, title: str | None = None) -> discord.Embed:
        embed = discord.Embed(title=title or "🍳 주방", color=0xFF8C00)
        
        if self.score == 0:
            time_str = "첫 주문!"
        else:
            t = (self.time_left // 10) * 10
            time_str = f"약 {t}초"

        embed.add_field(name="📊 현황", value=f"남은 시간: {time_str}　|　점수: {self.score}", inline=False)
        
        if self.is_away:
            order_display = "🏃 손님이 잠시 자리를 비웠습니다... (주문서 가려짐)"
        else:
            lines = []
            for i, o in enumerate(self.orders):
                if o["completed"]:
                    lines.append(f"~~{i+1}. {o['name']}~~ (서빙 완료!)")
                else:
                    lines.append(f"{i+1}. {o['name']}")
            order_display = "\n".join(lines)
            
        embed.add_field(name="🧑 손님 주문", value=order_display, inline=False)
        embed.add_field(name="💬 방금 전에...", value=self.last_event, inline=False)
        embed.add_field(name="🧊 냉장고", value=self.fridge_text(), inline=False)
        return embed

def make_guide_embed() -> discord.Embed:
    embed = discord.Embed(title="📜 주방 조리 가이드", color=0x3498DB)
    embed.add_field(name="[1. 냄비에 재료 넣기]", value="`[재료]를 넣고` \n`그 [재료]를 넣고` (손에 든 재료 사용)", inline=False)
    embed.add_field(name="[2. 조리 및 건지기]", value="`끓이고` 또는 `끓여서`\n`[재료]를 건져서` (진액만 건져냄. 남은 찌개 폐기!)", inline=False)
    embed.add_field(name="[3. 손님에게 내기]", value="`낸다` (손에 든 요리 제출)\n`[요리]를 낸다` (냉장고/냄비 지정 제출)", inline=False)
    embed.add_field(name="[4. 냉장고 보관소]", value="`담는다` : 빈칸 보관\n`[요리]를 꺼내서` : 복사\n`[요리]를 버린다` : 삭제", inline=False)
    return embed

def tokenize(text: str) -> list[tuple]:
    tokens: list[tuple] = []
    s = text.strip()
    while s:
        s = s.lstrip()
        if not s: break
        matched = False

        for ing in INGREDIENTS:
            for p in ["를", "을"]:
                patt = f"그 {ing}{p} 넣고"
                if s.startswith(patt):
                    tokens.append(("put_hand", ing))
                    s = s[len(patt):]
                    matched = True
                    break
            if matched: break
        if matched: continue

        if s.startswith("낸다."): tokens.append(("serve",)); s = s[3:]; continue
        if s.startswith("낸다"): tokens.append(("serve",)); s = s[2:]; continue
        if s.startswith("담는다."): tokens.append(("store",)); s = s[4:]; continue
        if s.startswith("담는다"): tokens.append(("store",)); s = s[3:]; continue
        if s.startswith("끓여서"): tokens.append(("boil",)); s = s[3:]; continue
        if s.startswith("끓이고"): tokens.append(("boil",)); s = s[3:]; continue
        if s.startswith("넣고"): tokens.append(("put_last",)); s = s[2:]; continue

        if s.startswith("냉장고를 비운다."): tokens.append(("empty_fridge",)); s = s[9:]; continue
        if s.startswith("냉장고를 비운다"): tokens.append(("empty_fridge",)); s = s[8:]; continue

        for ing in INGREDIENTS:
            for p in ["를", "을"]:
                patt = f"{ing}{p} 넣고"
                if s.startswith(patt):
                    tokens.append(("add", ing))
                    s = s[len(patt):]
                    matched = True
                    break
            if matched: break
        if matched: continue

        m_serve = re.match(r"^(.+?)[를을]\s*낸다\.?", s)
        if m_serve:
            name = m_serve.group(1).rstrip()
            s = s[len(m_serve.group(0)):]
            tokens.append(("serve_direct", name))
            continue

        m_trash = re.match(r"^(.+?)[를을]\s*버린다\.?", s)
        if m_trash:
            name = m_trash.group(1).rstrip()
            s = s[len(m_trash.group(0)):]
            tokens.append(("trash", name))
            continue

        m_fridge = re.match(r"^(.+?)[를을]\s*(꺼내서|꺼내고)", s)
        if m_fridge:
            name = m_fridge.group(1).rstrip()
            s = s[len(m_fridge.group(0)):]
            tokens.append(("take_fridge", name))
            continue

        m_extract = re.match(r"^(.+?)[를을]\s*(건져서|건지고)", s)
        if m_extract:
            name = m_extract.group(1).rstrip()
            s = s[len(m_extract.group(0)):]
            tokens.append(("extract", name))
            continue

        tokens.append(("error",))
        break
    return tokens

async def execute_token(tok: tuple, state: GameState) -> str:
    action = tok[0]

    def fail_order(msg: str) -> str:
        if state.score > 0:
            state.time_left = int(state.time_left * 0.9)

        state.pot_items = []
        state.pot_stew = None
        state.hand = {}
        state.last_hand_base = None

        ans = "\n".join(f"💡 {o['food']} 정답: {o['recipe']}" for o in state.orders if not o["completed"])

        if len(state.orders) > 1:
            f1 = state.orders[0]["food"]
            f2 = state.orders[1]["food"]
            fail_msg = state.current_template["fail"].format(food=f1, food2=f2)
            state.last_event = f"{msg}\n💬 \"{fail_msg}\"\n{ans}"
            return "stop" 
        else:
            state.last_event = f"{msg}\n{ans}"
            state.new_order(reset_time=False)
            return "fail_order" 

    def try_add_to_pot(name: str, dim: int, base: str) -> str:
        if state.pot_stew is not None:
            return fail_order("결국 냄비가 꽉 차서 타버렸다...")
        if any(p["base"] == base for p in state.pot_items):
            return fail_order(f"형용할 수 없는 무언가가 나와서 버렸다... (**{base}** 중복)")
        state.pot_items.append({"name": name, "dim": dim, "base": base})
        return "ok"

    if action == "error":
        return fail_order("결국 냄비가 타버렸다... 손님이 불평했다.")

    elif action == "add":
        ing = tok[1]
        if ing not in state.unlocked():
            state.last_event = f"**{ing}**는 아직 해금되지 않았다..."
            return "stop"
        result = try_add_to_pot(ing, 0, ing)
        if result == "ok": state.last_hand_base = None
        return result

    elif action == "put_hand":
        ing = tok[1]
        if ing not in state.hand:
            state.last_event = f"꺼내진 **{ing}**이/가 없다..."
            return "stop"
        item = state.hand[ing]
        result = try_add_to_pot(item["name"], item["dim"], ing)
        if result == "ok":
            del state.hand[ing]
            if state.last_hand_base == ing: state.last_hand_base = None
        return result

    elif action == "put_last":
        b = state.last_hand_base
        if not b or b not in state.hand:
            state.last_event = "방금 꺼낸 재료가 없다..."
            return "stop"
        item = state.hand[b]
        result = try_add_to_pot(item["name"], item["dim"], b)
        if result == "ok":
            del state.hand[b]
            state.last_hand_base = None
        return result

    elif action == "boil":
        if not state.pot_items:
            state.last_event = "냄비가 비어 있다..."
            return "stop"
        if state.pot_stew is not None:
            state.last_event = "이미 끓인 찌개가 있다..."
            return "stop"
        name = "".join(p["name"] for p in state.pot_items) + "찌개"
        dim = 1
        for p in state.pot_items:
            dim *= p["dim"] + 1
        if len(name) > state.max_name_len:
            return fail_order(f"결국 냄비가 타버렸다... {state.max_name_len}분을 더 끓여버린 듯 하다.")
        bases = [p["base"] for p in state.pot_items]
        state.pot_stew = {"name": name, "dim": dim, "bases": bases}
        state.pot_items = []
        return "ok"

    elif action == "extract":
        ing = tok[1]
        if state.pot_stew is None:
            if ing not in state.unlocked():
                state.last_event = f"**{ing}**는 아직 해금되지 않았다..."
                return "stop"
            if ing in state.hand:
                state.last_event = f"이미 꺼내진 **{ing}**이/가 있다..."
                return "stop"
            state.hand[ing] = {"name": ing, "base": ing, "dim": 0}
            state.last_hand_base = ing
            return "ok"

        if ing not in state.pot_stew["bases"]:
            state.last_event = f"찌개에 **{ing}**이/가 없다..."
            return "stop"
        if ing in state.hand:
            state.last_event = f"이미 꺼내진 **{ing}**이/가 있다..."
            return "stop"
        extracted_name = state.pot_stew["name"] + ing
        extracted_dim = state.pot_stew["dim"]
        state.hand[ing] = {"name": extracted_name, "dim": extracted_dim}
        state.last_hand_base = ing
        state.pot_stew = None
        return "ok"

    elif action == "take_fridge":
        dish_name = tok[1]
        slot_idx = next((i for i, s in enumerate(state.fridge) if s and s["name"] == dish_name), None)
        if slot_idx is None:
            state.last_event = f"냉장고에 **{dish_name}**이/가 없다..."
            return "stop"
        item = state.fridge[slot_idx]
        base = item["base"]
        if base in state.hand:
            state.last_event = f"이미 꺼내진 **{base}**이/가 있다..."
            return "stop"
        state.hand[base] = {"name": item["name"], "dim": item["dim"]}
        state.last_hand_base = base
        return "ok"

    elif action == "store":
        b = state.last_hand_base
        if not b or b not in state.hand:
            if len(state.hand) == 1: b = list(state.hand.keys())[0]
            else:
                state.last_event = "어떤 요리를 담을지 모르겠다... (방금 꺼낸 요리가 없거나 너무 많음)"
                return "stop"

        empty = next((i for i, s in enumerate(state.fridge) if s is None), None)
        if empty is None:
            state.last_event = "냉장고가 꽉 찼다..."
            return "stop"

        item = state.hand.pop(b)
        state.fridge[empty] = {"name": item["name"], "dim": item["dim"], "base": b}
        state.last_hand_base = None
        state.last_event = f"냉장고에 **{item['name']}**을/를 넣었다."
        return "ok"

    elif action in ("serve", "serve_direct"):
        served: dict | None = None
        
        if action == "serve":
            if state.pot_stew: served = state.pot_stew
            elif state.last_hand_base and state.last_hand_base in state.hand:
                served = state.hand[state.last_hand_base]
        else:
            dish_name = tok[1]
            if dish_name in INGREDIENTS:
                if dish_name not in state.unlocked():
                    state.last_event = f"**{dish_name}**는 아직 해금되지 않았다..."
                    return "stop"
                served = {"name": dish_name, "base": dish_name, "dim": 0}
            elif state.pot_stew and state.pot_stew["name"] == dish_name:
                served = state.pot_stew
            elif any(v["name"] == dish_name for v in state.hand.values()):
                b = next(k for k, v in state.hand.items() if v["name"] == dish_name)
                served = state.hand[b]
            else:
                slot_idx = next((i for i, slot in enumerate(state.fridge) if slot and slot["name"] == dish_name), None)
                if slot_idx is not None: served = state.fridge[slot_idx]

        if served is None:
            state.last_event = "낼 요리가 없거나 조건을 만족하지 않는다..."
            return "stop"

        served_matches = False
        target_order = None
        for order in state.orders:
            if not order["completed"] and served["name"] == order["food"]:
                served_matches = True
                target_order = order
                break
                
        if served_matches:
            pts = state.score_for(served["name"], served["dim"])
            target_order["earned_pts"] = pts
            target_order["completed"] = True
            state.score += pts
            
            all_completed = all(o["completed"] for o in state.orders)
            
            if all_completed:
                bonus_msg = ""
                # 💡 최초 재주문(다중 주문) 통과 시 알바생 고용 이벤트!
                if len(state.orders) > 1:
                    if not state.has_part_timer:
                        state.has_part_timer = True
                        bonus_msg = "\n🎉 **일손이 부족해 알바생을 하나 뽑았습니다! 이제 냉장고에 공간이 남아있다면 재료가 준비됩니다!**"
                    bonus = int(sum(o["earned_pts"] for o in state.orders) * 0.2)
                    state.score += bonus
                    state.last_event = f"💬 \"{target_order['success']}\"\n(결제 완료: 모든 요리 서빙 성공! 보너스 +{bonus}점!){bonus_msg}"
                    state.time_left = state.time_limit # 더블 제출 시 시간 풀회복
                else:
                    state.last_event = f"💬 \"{target_order['success']}\"\n(결제 완료: +{pts}점)"
                    
                state.pot_items = []
                state.pot_stew = None
                state.hand = {}
                state.last_hand_base = None
                state.is_away = False 
                
                state.new_order(reset_time=(len(state.orders) == 1))
                return "new_order"
            else:
                remain_food = next(o["food"] for o in state.orders if not o["completed"])
                msg = state.current_template["wait_next"].format(food_remain=remain_food)
                state.last_event = f"💬 \"{msg}\"\n(일단 하나 제출 성공! 나머지 요리를 서둘러야 한다.)"
                state.pot_items = []
                state.pot_stew = None
                state.hand = {}
                state.last_hand_base = None
                return "ok"
        else:
            return fail_order(state.current_template["wrong_order"].format(name=served['name']))

    elif action == "trash":
        dish_name = tok[1]
        hand_keys = [k for k, v in state.hand.items() if v["name"] == dish_name]
        if hand_keys:
            del state.hand[hand_keys[0]]
            if state.last_hand_base == hand_keys[0]: state.last_hand_base = None
            state.last_event = f"손에 들고 있던 **{dish_name}**을/를 쓰레기통에 버렸다."
            return "ok"

        slot_idx = next((i for i, s in enumerate(state.fridge) if s and s["name"] == dish_name), None)
        if slot_idx is not None:
            state.fridge[slot_idx] = None
            state.last_event = f"냉장고에서 **{dish_name}**을/를 빼서 쓰레기통에 버렸다."
            return "ok"

        state.last_event = f"버릴 **{dish_name}**이/가 손이나 냉장고에 없다..."
        return "stop"

    elif action == "empty_fridge":
        state.fridge = [None] * 7
        state.last_event = "냉장고를 싹 비웠다!"
        return "ok"

    return "ok"

async def process_input(state: GameState, text: str, channel: discord.TextChannel) -> None:
    if state.user_id not in active_kitchen_games: return

    tokens = tokenize(text)
    if any(tok[0] == "error" for tok in tokens):
        state.last_event = "너무 허둥지둥한 나머지 뭔가 실수한 것 같다... 처음부터 다시 해보자..."
        await update_embed(state)
        return

    if not tokens or tokens[-1][0] not in ("serve", "store", "serve_direct", "trash", "empty_fridge"):
        state.last_event = "너무 허둥지둥한 나머지 다 끓이기도 전에 요리를 마쳐버렸다... 처음부터 다시 해보자..."
        await update_embed(state)
        return

    backup_pot_items = [dict(p) for p in state.pot_items]
    backup_pot_stew = dict(state.pot_stew) if state.pot_stew else None
    backup_hand = {k: dict(v) for k, v in state.hand.items()}
    backup_last_hand_base = state.last_hand_base
    backup_fridge = [(dict(item) if item else None) for item in state.fridge]
    backup_score = state.score

    result = "ok"
    for tok in tokens:
        result = await execute_token(tok, state)
        if result in ("stop", "end", "new_order", "fail_order"):
            break

    if result in ("stop", "fail_order"):
        state.pot_items = backup_pot_items
        state.pot_stew = backup_pot_stew
        state.hand = backup_hand
        state.last_hand_base = backup_last_hand_base
        state.fridge = backup_fridge
        if result == "stop":
            state.score = backup_score

    await update_embed(state)

    if result == "end":
        await end_game(state, channel)
    elif result == "new_order":
        if state.timer_task: state.timer_task.cancel()
        state.timer_task = asyncio.create_task(timer_loop(state, channel))

async def timer_loop(state: GameState, channel: discord.TextChannel) -> None:
    try:
        while state.time_left > 0:
            await asyncio.sleep(1)

            if state.score > 0:
                state.time_left -= 1

                if state.time_left % 10 == 0:
                    if state.is_away:
                        if state.time_left <= 20 or random.random() < 0.5:
                            state.is_away = False
                            add_prob = state.get_features()["add_prob"]
                            
                            if random.random() < add_prob and len(state.orders) == 1: 
                                add_len = max(2, (state.max_name_len // 2) & ~1)
                                new_ord = state.generate_single_order(add_len)
                                new_ord["name"] = f"(추가) {new_ord['food']}"
                                state.orders.append(new_ord)
                                
                                msg = state.current_template["return_add"].format(food2=new_ord["food"])
                                state.last_event = f"🏃 손님 복귀 및 추가 주문!\n💬 \"{msg}\""
                            else:
                                msg = state.current_template["return_normal"].format(food=state.orders[0]["food"])
                                state.last_event = f"🏃 손님 복귀!\n💬 \"{msg}\""
                    
                    elif state.time_left == state.time_limit - 20 and state.time_limit >= 30 and len(state.orders) == 1:
                        away_prob = state.get_features()["away_prob"]
                        if random.random() < away_prob:
                            state.is_away = True
                            msg = state.current_template["away"]
                            state.last_event = f"💨 손님이 자리를 비웠다!\n💬 \"{msg}\""

                    await update_embed(state)

        if any(o["completed"] for o in state.orders):
            msg = state.current_template["timeout_partial"]
            ans = "\n".join(f"💡 {o['food']} 정답: {o['recipe']}" for o in state.orders if not o["completed"])
            state.last_event = f"💬 \"{msg}\"\n{ans}"
        else:
            ans = "\n".join(f"💡 {o['food']} 정답: {o['recipe']}" for o in state.orders)
            state.last_event = f"{state.current_template['timeout_failure']}\n{ans}"
        await end_game(state, channel)
    except asyncio.CancelledError:
        pass

async def update_embed(state: GameState) -> None:
    if state.user_id not in active_kitchen_games: return 
    if state.embed_msg:
        try:
            await state.embed_msg.edit(embeds=[make_guide_embed(), state.make_embed()])
        except Exception:
            pass

async def end_game(state: GameState, channel: discord.TextChannel) -> None:
    uid_int = state.user_id
    if uid_int not in active_kitchen_games: return

    active_kitchen_games.pop(uid_int, None)
    if state.timer_task and state.timer_task is not asyncio.current_task():
        state.timer_task.cancel()

    score = state.score
    uid_str = str(uid_int)

    if score > 0:
        user_scores = await async_check_level(uid_str)
        earned_chips = score
        bonus = apply_game_reward(user_scores, earned_chips, exp_rate=0.2)
        bonus_str = f" (부스터 +{bonus})" if bonus > 0 else ""
        
        await async_save_scores(uid_str, user_scores)
        reward_text = f"\n💰 정산 완료: 칩 +{earned_chips}{bonus_str}\n(보유 칩: {user_scores['chips']})"
        
        rank = await save_and_get_weekly_ranking(uid_int, state.user_name, score)
        if 0 < rank <= 3:
            ranking_data = {}
            if os.path.exists(RANKING_FILE):
                with open(RANKING_FILE, "r", encoding="utf-8") as f:
                    ranking_data = json.load(f).get("scores", {})
            
            sorted_scores = sorted(ranking_data.values(), key=lambda x: x["score"], reverse=True)[:3]
            rank_text = "\n\n🏆 **[이번 주 주간 랭킹 TOP 3]** 🏆\n"
            for i, entry in enumerate(sorted_scores):
                rank_text += f"{i+1}위. {entry['name']} ({entry['score']}점)\n"
            reward_text += rank_text
    else:
        reward_text = "\n💸 획득한 점수가 없어 보상이 없습니다..."

    embed = state.make_embed(title=f"🍽️ 영업 종료! 최종 점수: {score}")
    embed.description = reward_text

    if state.embed_msg:
        try:
            await state.embed_msg.delete()
        except Exception:
            pass

    try:
        await channel.send(embed=embed)
    except Exception:
        pass
class KitchenCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot: return
        uid = message.author.id
        if uid not in active_kitchen_games: return
        if message.content.startswith("손목걸고"): return
        
        state = active_kitchen_games[uid]
        if message.channel.id != state.channel_id: return
        
        try:
            await message.delete()
        except discord.Forbidden:
            pass 
        
        async with state.lock:
            await process_input(state, message.content, message.channel)

    @commands.command(name="주방입장")
    async def join_kitchen(self, ctx: commands.Context) -> None:
        uid = ctx.author.id
        if uid in active_kitchen_games:
            await ctx.send("이미 주방에서 요리 중입니다!", delete_after=5)
            return
        state = GameState(uid, ctx.author.display_name, ctx.channel.id)
        state.new_order()
        active_kitchen_games[uid] = state
        embed = state.make_embed(title="🍳 주방에 입장했습니다!")
        msg = await ctx.send(embeds=[make_guide_embed(), embed])
        state.embed_msg = msg
        state.timer_task = asyncio.create_task(timer_loop(state, ctx.channel))

    @commands.command(name="주방퇴장")
    async def leave_kitchen(self, ctx: commands.Context) -> None:
        uid = ctx.author.id
        if uid not in active_kitchen_games:
            await ctx.send("현재 주방에 없습니다.", delete_after=5)
            return
        state = active_kitchen_games[uid]
        ans = "\n".join(f"💡 {o['food']} 정답: {o['recipe']}" for o in state.orders if not o["completed"])
        state.last_event = f"스스로 주방을 떠났다...\n{ans}"
        await end_game(state, ctx.channel)

async def setup(bot):
    await bot.add_cog(KitchenCog(bot))