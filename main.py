import aiohttp
import logging
import datetime
from typing import Optional, List, Dict
import traceback

from astrbot.api.all import (
    Star, Context, register,
    AstrMessageEvent, command_group, command,
    MessageEventResult, llm_tool
)
from astrbot.api.event import filter

# ==============================
# 1) HTML 模板
# ==============================

CURRENT_WEATHER_TEMPLATE = """
<html>
<head>
  <meta charset="UTF-8"/>
  <style>
    html, body {
      margin: 0;
      padding: 0;
      width: 1280px; /* 确保匹配 render 预设的图片尺寸 */
      height: 720px;
      background-color: #fff;
    }
    .weather-container {
      width: 100%;
      height: 100%;
      padding: 8px;
      display: flex;
      flex-direction: column;
      justify-content: center; /* 垂直居中 */
      align-items: center; /* 水平居中 */
      background-color: #ffffff;
      color: #333;
      font-family: sans-serif;
      font-size: 30px;
      border: 1px solid #ddd;
      border-radius: 8px;
    }
    .weather-container h2 {
      margin-top: 0;
      color: #4e6ef2;
      text-align: center;
      font-size: 40px;
    }
    .weather-info {
      margin-bottom: 10px;
    }
    .source-info {
      border-top: 1px solid #ddd;
      margin-top: 12px;
      padding-top: 12px;
      font-size: 16px;
      color: #999;
    }
  </style>
</head>
<body>
  <div class="weather-container">
    <h2>当前天气</h2>
    
    <div class="weather-info">
      <strong>城市:</strong> {{ city }}
    </div>
    <div class="weather-info">
      <strong>天气:</strong> {{ desc }}
    </div>
    <div class="weather-info">
      <strong>温度:</strong> {{ temp }}℃ (体感: {{ feels_like }}℃)
    </div>
    <div class="weather-info">
      <strong>湿度:</strong> {{ humidity }}%
    </div>
    <div class="weather-info">
      <strong>风速:</strong> {{ wind_speed }} km/h
    </div>
    
    <div class="source-info">
      数据来源: 心知天气（Seniverse） 免费API
    </div>
  </div>
</body>
</html>
"""

FORECAST_TEMPLATE = """
<html>
<head>
  <meta charset="UTF-8"/>
  <style>
    html, body {
      margin: 0;
      padding: 0;
      width: 1280px;
      height: 720px;
      background-color: #fff;
    }
    .forecast-container {
      width: 100%;
      height: 100%;
      padding: 8px;
      display: flex;
      flex-direction: column;
      justify-content: center;
      align-items: center;
      background-color: #fff;
      color: #333;
      font-family: sans-serif;
      font-size: 30px;
      border: 1px solid #ddd;
      border-radius: 8px;
    }
    .forecast-container h2 {
      margin-top: 0;
      color: #4e6ef2;
      text-align: center;
      font-size: 40px;
    }
    .city-info {
      margin-bottom: 8px;
    }
    .day-item {
      margin-bottom: 8px;
      border-bottom: 1px solid #eee;
      padding-bottom: 4px;
    }
    .day-title {
      font-weight: bold;
      color: #4e6ef2;
      margin-bottom: 4px;
    }
    .source-info {
      font-size: 16px;
      color: #999;
      margin-top: 12px;
      border-top: 1px solid #ddd;
      padding-top: 8px;
    }
  </style>
</head>
<body>
  <div class="forecast-container">
    <h2>未来{{ total_days }}天天气预报</h2>
    <div class="city-info">
      <strong>城市:</strong> {{ city }}
    </div>

    {% for day in days %}
    <div class="day-item">
      <div class="day-title">{{ day.date }}</div>
      <div><strong>白天:</strong> {{ day.text_day }} — {{ day.high }}℃</div>
      <div><strong>夜晚:</strong> {{ day.text_night }} — {{ day.low }}℃</div>
      <div><strong>湿度:</strong> {{ day.humidity }}%  <strong>风速:</strong> {{ day.wind_speed }} km/h</div>
    </div>
    {% endfor %}

    <div class="source-info">
      数据来源: 心知天气（Seniverse） 免费API
    </div>
  </div>
</body>
</html>
"""

@register(
    "astrbot_plugin_weather",
    "w33d",
    "一个基于心知天气（Seniverse）免费API的天气查询插件",
    "2.1.1",
    "https://github.com/Last-emo-boy/astrbot_plugin_weather"
)
class WeatherPlugin(Star):
    """
    这是一个调用心知天气（Seniverse）免费版 API 的天气查询插件示例。
    支持 /weather current /weather forecast /weather help
    - current: 查询当前实况
    - forecast: 查询未来3天天气预报及生活指数
    """
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.logger = logging.getLogger("WeatherPlugin")
        self.logger.setLevel(logging.DEBUG)
        self.config = config
        # 使用配置中的 seniverse_api_key
        self.api_key = config.get("seniverse_api_key", "")
        self.default_city = config.get("default_city", "北京")
        # 新增配置项：send_mode，控制发送模式 "image" 或 "text"
        self.send_mode = config.get("send_mode", "image")
        self.logger.debug(f"WeatherPlugin initialized with API key: {self.api_key}, default_city: {self.default_city}, send_mode: {self.send_mode}")

    # =============================
    # 命令组 "weather"
    # =============================
    @command_group("weather")
    def weather_group(self):
        """
        天气相关功能命令组。
        使用方法：
        /weather <子指令> <城市或其它参数>
        子指令包括：current, forecast, help
        """
        pass

    @weather_group.command("current")
    async def weather_current(self, event: AstrMessageEvent, city: Optional[str] = None):
        """
        查看当前实况天气
        用法: /weather current <城市>
        示例: /weather current 北京
        """
        self.logger.info(f"User called /weather current with city={city}")
        if not city:
            city = self.default_city
        if not self.api_key:
            yield event.plain_result("未配置 Seniverse API Key，无法查询天气。请在管理面板中配置后再试。")
            return
        data = await self.get_current_weather_by_city(city)
        if data is None:
            yield event.plain_result(f"查询 [{city}] 的当前天气失败，请稍后再试。")
            return
        # 根据配置决定发送模式
        if self.send_mode == "image":
            result_img_url = await self.render_current_weather(data)
            yield event.image_result(result_img_url)
        else:
            text = (
                f"当前天气：\n"
                f"城市: {data['city']}\n"
                f"天气: {data['desc']}\n"
                f"温度: {data['temp']}℃ (体感: {data['feels_like']}℃)\n"
                f"湿度: {data['humidity']}%\n"
                f"风速: {data['wind_speed']} km/h"
            )
            yield event.plain_result(text)

    @weather_group.command("forecast")
    async def weather_forecast(self, event: AstrMessageEvent, city: Optional[str] = None):
        """
        查看未来3天天气预报及生活指数
        用法: /weather forecast <城市>
        示例: /weather forecast 北京
        """
        self.logger.info(f"User called /weather forecast with city={city}")
        if not city:
            city = self.default_city
        if not self.api_key:
            yield event.plain_result("未配置 Seniverse API Key，无法查询天气。请在管理面板中配置后再试。")
            return
        forecast_data = await self.get_forecast_weather_by_city(city)
        if forecast_data is None:
            yield event.plain_result(f"查询 [{city}] 的未来天气失败，请稍后再试。")
            return
        suggestion_data = await self.get_life_suggestion_by_city(city)
        # 根据配置决定发送模式
        if self.send_mode == "image":
            forecast_img_url = await self.render_forecast_weather(
                city,
                days_data=forecast_data,
                suggestions=suggestion_data
            )
            yield event.image_result(forecast_img_url)
        else:
            text = f"未来{len(forecast_data)}天天气预报\n城市: {city}\n"
            for day in forecast_data:
                text += (
                    f"{day['date']}: 白天: {day['text_day']} - {day['high']}℃, "
                    f"夜晚: {day['text_night']} - {day['low']}℃, "
                    f"湿度: {day['humidity']}%, "
                    f"风速: {day['wind_speed']} km/h\n"
                )
            if suggestion_data:
                text += "生活指数:\n"
                for s in suggestion_data:
                    text += f"{s['name']}: {s['brief']}\n"
            yield event.plain_result(text)

    @weather_group.command("help")
    async def weather_help(self, event: AstrMessageEvent):
        """
        显示天气插件的帮助信息
        用法: /weather help
        """
        self.logger.info("User called /weather help")
        msg = (
            "=== 心知天气插件命令列表 ===\n"
            "/weather current <城市>  查看当前实况\n"
            "/weather forecast <城市> 查看未来3天天气预报及生活指数\n"
            "/weather help            显示本帮助\n"
        )
        yield event.plain_result(msg)

    # =============================
    # LLM Function-Calling (可选)
    # =============================
    @llm_tool(name="get_current_weather")
    async def get_current_weather_tool(self, event: AstrMessageEvent, city: str) -> MessageEventResult:
        '''当用户对某个城市的天气情况感兴趣时，用于获取当前天气信息。

        Args:
            city (string): 地点，例如：杭州，或者浙江杭州
        '''
        if not city:
            city = self.default_city
        data = await self.get_current_weather_by_city(city)
        if not data:
            yield event.plain_result(f"查询 [{city}] 天气失败，请稍后再试。")
            return
        if self.send_mode == "image":
            url = await self.render_current_weather(data)
            yield event.image_result(url)
        else:
            text = (
                f"当前天气：\n"
                f"城市: {data['city']}\n"
                f"天气: {data['desc']}\n"
                f"温度: {data['temp']}℃ (体感: {data['feels_like']}℃)\n"
                f"湿度: {data['humidity']}%\n"
                f"风速: {data['wind_speed']} km/h"
            )
            yield event.plain_result(text)

    @llm_tool(name="get_forecast_weather")
    async def get_forecast_weather_tool(self, event: AstrMessageEvent, city: str) -> MessageEventResult:
        '''当用户对某个城市未来天气预报感兴趣时，用于获取天气预报信息。

        Args:
            city (string): 地点，例如：杭州，或者浙江杭州
        '''
        if not city:
            city = self.default_city
        forecast_data = await self.get_forecast_weather_by_city(city)
        suggestion_data = await self.get_life_suggestion_by_city(city)
        if not forecast_data:
            yield event.plain_result(f"查询 [{city}] 天气失败，请稍后再试。")
            return
        if self.send_mode == "image":
            url = await self.render_forecast_weather(city, forecast_data, suggestion_data)
            yield event.image_result(url)
        else:
            text = f"未来{len(forecast_data)}天天气预报\n城市: {city}\n"
            for day in forecast_data:
                text += (
                    f"{day['date']}: 白天: {day['text_day']} - {day['high']}℃, "
                    f"夜晚: {day['text_night']} - {day['low']}℃, "
                    f"湿度: {day['humidity']}%, "
                    f"风速: {day['wind_speed']} km/h\n"
                )
            if suggestion_data:
                text += "生活指数:\n"
                for s in suggestion_data:
                    text += f"{s['name']}: {s['brief']}\n"
            yield event.plain_result(text)

    # =============================
    # 核心逻辑
    # =============================
    async def get_current_weather_by_city(self, city: str) -> Optional[dict]:
        """
        调用心知天气 v3/weather/now.json 接口，返回城市当前实况
        """
        self.logger.debug(f"get_current_weather_by_city city={city}")
        url = "https://api.seniverse.com/v3/weather/now.json"
        params = {
            "key": self.api_key,
            "location": city,
            "language": "zh-Hans",
            "unit": "c"
        }
        self.logger.debug(f"Requesting: {url}, params={params}")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=10) as resp:
                    self.logger.debug(f"Response status: {resp.status}")
                    if resp.status == 200:
                        data = await resp.json()
                        self.logger.debug(f"Seniverse now raw data: {data}")
                        results = data.get("results", [])
                        if not results:
                            return None
                        now = results[0].get("now", {})
                        desc = now.get("text", "未知")
                        temp = now.get("temperature", "0")
                        feels_like = now.get("feels_like", temp)
                        humidity = now.get("humidity", "0")
                        wind_speed = now.get("wind_speed", "0")
                        return {
                            "city": city,
                            "desc": desc,
                            "temp": temp,
                            "feels_like": feels_like,
                            "humidity": humidity,
                            "wind_speed": wind_speed
                        }
                    else:
                        self.logger.error(f"get_current_weather_by_city status={resp.status}")
                        return None
        except Exception as e:
            self.logger.error(f"get_current_weather_by_city error: {e}")
            self.logger.error(traceback.format_exc())
            return None

    async def get_forecast_weather_by_city(self, city: str) -> Optional[List[dict]]:
        """
        调用心知天气 v3/weather/daily.json 接口，获取3天天气预报
        """
        self.logger.debug(f"get_forecast_weather_by_city city={city}")
        url = "https://api.seniverse.com/v3/weather/daily.json"
        params = {
            "key": self.api_key,
            "location": city,
            "language": "zh-Hans",
            "unit": "c",
            "start": 0,
            "days": 3
        }
        self.logger.debug(f"Requesting forecast: {url}, params={params}")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=10) as resp:
                    self.logger.debug(f"Response status: {resp.status}")
                    if resp.status == 200:
                        data = await resp.json()
                        self.logger.debug(f"Seniverse daily raw data: {data}")
                        results = data.get("results", [])
                        if not results:
                            return None
                        daily_list = results[0].get("daily", [])
                        if not daily_list:
                            return None
                        result = []
                        for day_data in daily_list:
                            date = day_data.get("date", "1970-01-01")
                            text_day = day_data.get("text_day", "未知")
                            text_night = day_data.get("text_night", "未知")
                            high = day_data.get("high", "0")
                            low = day_data.get("low", "0")
                            humidity = day_data.get("humidity", "0")
                            wind_speed = day_data.get("wind_speed", "0")
                            result.append({
                                "date": date,
                                "text_day": text_day,
                                "text_night": text_night,
                                "high": high,
                                "low": low,
                                "humidity": humidity,
                                "wind_speed": wind_speed
                            })
                        return result
                    else:
                        self.logger.error(f"get_forecast_weather_by_city status={resp.status}")
                        return None
        except Exception as e:
            self.logger.error(f"get_forecast_weather_by_city error: {e}")
            self.logger.error(traceback.format_exc())
            return None

    async def get_life_suggestion_by_city(self, city: str) -> Optional[List[dict]]:
        """
        调用心知天气 v3/life/suggestion.json 接口，获取生活指数
        免费版仅返回6项基础指数 (dressing, umbrella, car_washing, flu, sport, uv)，且只包含 brief 信息
        """
        self.logger.debug(f"get_life_suggestion_by_city city={city}")
        url = "https://api.seniverse.com/v3/life/suggestion.json"
        params = {
            "key": self.api_key,
            "location": city,
            "language": "zh-Hans",
            "days": 1
        }
        self.logger.debug(f"Requesting life suggestion: {url}, params={params}")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=10) as resp:
                    self.logger.debug(f"Response status: {resp.status}")
                    if resp.status == 200:
                        data = await resp.json()
                        self.logger.debug(f"Seniverse suggestion raw data: {data}")
                        results = data.get("results", [])
                        if not results:
                            return None
                        suggestion = results[0].get("suggestion", {})
                        if not suggestion:
                            return None
                        final_list = []
                        for key in ["dressing", "umbrella", "car_washing", "flu", "sport", "uv"]:
                            info = suggestion.get(key, {})
                            brief = info.get("brief", "无")
                            cn_name = self.get_suggestion_cn_name(key)
                            final_list.append({"name": cn_name, "brief": brief})
                        return final_list
                    else:
                        self.logger.error(f"get_life_suggestion_by_city status={resp.status}")
                        return None
        except Exception as e:
            self.logger.error(f"get_life_suggestion_by_city error: {e}")
            self.logger.error(traceback.format_exc())
            return None

    def get_suggestion_cn_name(self, key: str) -> str:
        """
        将英文指数 key 映射为直观的中文名称
        """
        mapping = {
            "dressing": "穿衣",
            "umbrella": "雨伞",
            "car_washing": "洗车",
            "flu": "感冒",
            "sport": "运动",
            "uv": "紫外线"
        }
        return mapping.get(key, key)

    # =============================
    # 渲染逻辑
    # =============================
    async def render_current_weather(self, data: dict) -> str:
        """
        渲染当前天气图文信息
        """
        self.logger.debug(f"render_current_weather for {data}")
        url = await self.html_render(
            CURRENT_WEATHER_TEMPLATE,
            {
                "city": data["city"],
                "desc": data["desc"],
                "temp": data["temp"],
                "feels_like": data["feels_like"],
                "humidity": data["humidity"],
                "wind_speed": data["wind_speed"]
            },
            return_url=True
        )
        return url

    async def render_forecast_weather(self, city: str, days_data: List[dict], suggestions: Optional[List[dict]] = None) -> str:
        """
        渲染未来3天天气预报及生活指数图文信息
        """
        self.logger.debug(f"render_forecast_weather for city={city}, days={days_data}, suggestions={suggestions}")
        url = await self.html_render(
            FORECAST_TEMPLATE,
            {
                "city": city,
                "days": days_data,
                "total_days": len(days_data),
                "suggestions": suggestions or []
            },
            return_url=True
        )
        return url
