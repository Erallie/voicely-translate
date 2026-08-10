# Voicely Translate

[![Invite Me](https://img.shields.io/badge/Invite%20Me-7965c7?style=for-the-badge)](https://discord.com/oauth2/authorize?client_id=1535789654974930964)
[![App Directory](https://img.shields.io/badge/App%20Directory-615ccc?style=for-the-badge)](https://discord.com/application-directory/1535789654974930964)
[![Privacy Policy](https://img.shields.io/badge/Privacy%20Policy-cc7a7c?style=for-the-badge)](https://github.com/Erallie/voicely-translate/blob/main/legal/privacy-policy.md)
<br>
[![Our Discord](https://img.shields.io/discord/1102582171207741480?style=for-the-badge&logo=discord&logoColor=ffffff&label=Our%20Discord&color=5865F2)](https://discord.gozarproductions.com)
[![Our Other Projects](https://img.shields.io/badge/Our%20Other%20Projects-%E2%9D%A4-563294?style=for-the-badge&logo=data%3Aimage%2Fwebp%3Bbase64%2CUklGRu4DAABXRUJQVlA4WAoAAAAQAAAAHwAAHwAAQUxQSGABAAABgFtbm5volyZTA%2BtibzK2H0w5sDkmhe3GmxrwxGg0839r%2FvkkOogIBW7bKB0c4%2BARYihzIqfd6dfO%2B%2B3XtHsq4jJhlIvcDRcgNB%2FeieQETorBHgghRtUYqwDs%2B4U4IpcvUB%2BVUPSK54uEnTwsUJoar2DeMpzLxQpeG5DH8lxyyfLivVYAwPBbkWdOBg3qFlqiLy679iHy9UDKMZRXmYxpCcusayTHG01K%2FEtatYWuj7oI9hL4BxsxVwhoP2mlAJJ%2BuuAflc6%2BEUCQTCX9EV87xBR2H75NxLZSpWiwzqdIm7ZO7uB3oEgZKbD9Nt3EmHweEPH1t1GNsZUbKeisiwjyTm5fA3SO1yCrADZXrV2PZQJPL1tjN4%2BxUL9ie1mJobzOnDwSx6ILiF%2FW%2BTUR4tcHx0UaV75JXC1a4g6Ky5dLcTSuy9q4HhTieF64Hy1A3GHB8gLLK2e92feuqnbfPK8IVlA4IGgCAACwDQCdASogACAAPk0cjEQioaEb%2BqwAKATEtgBOl7v9V3sHcA2wG4A3gD0APLP9jX9n%2F2jmqv5AZRh7J%2BN2fOx22iE%2F4TUsecFmY%2BSf1r%2BAP%2BTfzT%2FXdIB7KX7MtdIGr1A8H0jmrrfZvqButwOaYcLWYNRq5QgAAP7%2F%2FmIMpiVNn67QXpM1rrDmRS8Nr%2F6dhD%2Bq5e%2BM%2BAtUP1%2FxOj85Ol5y3ebjz%2BpHoOf%2FWW8a%2F2ojUaKVDkVqof%2Bv4f0f6ud8i58wusz%2Fyrj%2F%2BwnM3q0769dvK%2F%2BQe04xL49tkb9t6ylCqqezZtZGuGLJ%2F5iUrPqdYc%2F8VbYZfP%2FOpZP%2F4X4q%2BqS4gPOxzdINOe5PGv%2F0TS%2FJRf4LlFrFkrWtxlS8n40grV%2BKUu%2FiwzdQzImvwH81FxL1bZyTSsrYwMku1Pk9StTtWNjSR8ZWEYBH9eTn%2FvBERii5XaWOPJ%2FFVXtVQGbv%2BFRW5jbo9tfFDu%2BDHHf8LbgUd%2F8W8Id1AehBtRNsLQWbADmvF1QJU8x5tw%2FtTUwIoSaa%2F2jkcvyVHkAsb2qoIh1KF1pPdae%2BZaqjydy6nUa9agjrDk1G4pMhEUhH%2BV%2FIUe49MjhR%2FuxyFmwQ8dDogMyQ%2BdcSBa56Lwt1wyJ%2F22%2F5O98r6q6wiM63HyaYONd36W7br%2F0%2F6y2DZ3irAddj%2FRxntvr%2FbbChSYXAfEbO%2FD0G%2FFbMFqTHypodt9T6dAx%2BUjJYfHzFf%2FM3Ec%2FAtwbjc2gka6urN1MlSLb2VTS9Q5r8fkDzxZz6vu1OYUPUB1UFMIhYGvMATbxxoTmVhvpovzAc%2F8nbOjw3wAAA)](https://github.com/Erallie)
[![Donate](https://img.shields.io/badge/Donate-%24-563294?style=for-the-badge&logo=ko-fi&logoColor=FFFFFF&color=FF6433)](https://www.ko-fi.com/GozarProductions)

---

## 用户指南

Voicely Translate 是一个 Discord 机器人，可自动转录语音频道中的对话并翻译成多种语言。每位说话者的音频都会单独处理，因此可支持多人同时或重叠说话，结果会发布到该语音频道的侧边聊天中。

## 功能
* 自动语音转录和多语言翻译。
* 同时启用多个目标语言。
* 会话进行中添加或移除语言。
* 使用 BCP 47 语言标签，不受固定列表限制。
* 语音频道无人后按设定时间自动离开。
* 可搭配 [**Voicely Text**](https://discord.com/application-directory/1290741552158609419) 朗读翻译。

## 安装与开始
使用[邀请链接](https://discord.com/oauth2/authorize?client_id=1535789654974930964)添加机器人，加入普通语音频道，然后运行 `/join languages:en,ja`。多个标签用逗号分隔。转录和翻译会发布到**该语音频道的侧边聊天**。

`/languages` 会显示 `en`、`ja`、`es`、`fr`、`de`、`ko`、`zh`、`haw` 等常用标签。也可以使用 `pt-BR`、`zh-TW` 等区域标签。显示的列表不是限制列表。

## 更改语言
`/add languages:fr,ko` 添加语言；`/remove languages:en,fr` 移除语言；`/active` 查看当前语言；`/leave` 停止并离开。

## 空频道超时
管理员可使用 `/timeout seconds:60` 设置等待时间。默认值为 **30 秒**。

## Voicely Credits
**100 Voicely Credits = 1.00 美元**。新服务器目前获得 **50 个免费试用点数**。转录和翻译会消耗点数，启用更多目标语言可能增加用量。

`/balance` 显示可用、试用和已购买点数。`/usage` 显示 API 总用量、转录用量、翻译用量和购买总量。点数属于 **Discord 服务器**，而不是个人用户。

管理员使用 `/topup` 获取服务器专用代码并通过 Ko-fi 充值。**每 1.00 美元增加 100 点数**。付款留言中必须准确填写代码，之后使用 `/balance` 或 `/join`。

## 工作方式
1. 接收每位说话者的音频。
2. 按实际说出的语言转录。
3. 翻译为已启用的语言。
4. 将原文和翻译发布到侧边聊天。

短暂停顿用于判断一句话结束。纯非语言声音或单独的犹豫声可能会被忽略。

## 命令
`/join` 开始 · `/add` 添加 · `/remove` 移除 · `/active` 当前语言 · `/languages` 标签参考 · `/leave` 结束 · `/balance` 余额 · `/usage` 用量 · `/topup` 充值（管理员） · `/timeout` 超时（管理员）。

## 质量与隐私
请清晰说话并避免过大的背景音乐或噪声。自动转录和翻译可能在姓名、俚语、很短或模糊的语音上出错。机器人必须处理语音才能提供服务；在机器人存在期间，应让频道成员知道对话正在被转录。

# 支持
如果机器人出现问题或你想请求新功能，请创建一个 [issue](https://github.com/Erallie/voicely-translate/issues)，我会尽力处理！
