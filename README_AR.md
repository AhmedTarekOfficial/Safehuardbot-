# Sentinel Bot — دليل التشغيل بالعربي

ده مشروع Discord Bot لإدارة وحماية السيرفر، مكتوب بـ **Python** و **discord.py**.

## 1) إنشاء البوت

1. افتح https://discord.com/developers/applications
2. اختار **New Application**، وسميها Sentinel أو أي اسم تحبه.
3. من صفحة **Bot** اعمل Reset Token أو Copy Token. **ما تبعتش Token لأي حد، ومتعملوش Push على GitHub**.
4. في نفس صفحة Bot، شغّل:
   - **Server Members Intent**: لمراقبة الدخول المفاجئ لأعضاء كتير.
   - **Message Content Intent**: لمراقبة Spam وروابط الدعوات.
5. من **OAuth2 / URL Generator** أو **Installation** اختار الـ scopes: `bot` و `applications.commands`.
6. ادّي البوت الصلاحيات المناسبة: **Manage Roles, Kick Members, Ban Members, Moderate Members, Manage Messages, Read Message History, View Channels, Send Messages, Embed Links**.
7. ادخل البوت لسيرفرك. خلي Role بتاعه **أعلى من الرولات اللي المفروض يديرها** لكن من غير ما تديله Administrator لو مش محتاج.

## 2) تشغيل المشروع

نزّل Python 3.11 أو أحدث، وفك ضغط المشروع، وافتح Terminal داخل فولدر `sentinel-discord-bot`.

على Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

افتح ملف `.env`، وغير:

```dotenv
DISCORD_TOKEN=PUT_YOUR_REAL_BOT_TOKEN_HERE
DEV_GUILD_ID=YOUR_SERVER_ID
```

الـ `DEV_GUILD_ID` اختياري، لكنه بيخلي أوامر Slash تظهر أسرع في السيرفر اللي بتجرب فيه. تقدر تجيب Server ID من Discord بعد تفعيل Developer Mode. **متشاركش ملف `.env`**.

بعدها شغّل:

```powershell
python main.py
```

على Linux أو macOS نفس الخطوات لكن تفعيل البيئة الافتراضية يكون:

```bash
source .venv/bin/activate
```

## 3) الأوامر

| الأمر | الوظيفة |
| --- | --- |
| `/helpbot` | عرض الأوامر |
| `/role add` | إضافة رول لعضو |
| `/role remove` | إزالة رول |
| `/kick` | إخراج عضو |
| `/ban` | حظر عضو |
| `/unban` | فك الحظر باستخدام User ID |
| `/timeout` | Timeout بالدقايق لحد 28 يوم |
| `/untimeout` | إلغاء Timeout |
| `/purge` | حذف 1–100 رسالة |
| `/permissions` | فتح Panel عرض الصلاحيات والبحث |
| `/guard logs` | تحديد قناة الـ Logs |
| `/guard antispam` | تفعيل/تعطيل مقاومة Spam |
| `/guard links` | تفعيل/تعطيل حذف روابط دعوات Discord |
| `/guard raid` | تفعيل/تعطيل تنبيهات دخول الأعضاء بسرعة |
| `/guard status` | عرض إعدادات الحماية |
| `/guard clearlogs` | إلغاء قناة Logs |

## 4) مثال إعداد الحماية

بعد ما تعمل قناة مثلاً `#mod-logs`:

```text
/guard logs channel:#mod-logs
/guard antispam enabled:True
/guard links enabled:True
/guard raid enabled:True
```

التلات خصائص بيكونوا **OFF افتراضيًا**. إعداداتهم بتتحفظ حتى بعد Restart.

### تفاصيل الحماية

- **Anti-spam:** لو العضو أرسل 7 رسائل في 8 ثوانٍ، أو كرر نفس الرسالة 4 مرات في 12 ثانية، أو عمل Mention لـ 8 أعضاء في رسالة، البوت يحاول يحذف الرسالة ويعمل Timeout لمدة 10 دقايق. أصحاب صلاحية Manage Messages في نفس القناة مستثنين.
- **Invite filter:** حذف رسائل روابط دعوات Discord، مش كل الروابط.
- **Raid detection:** لو 8 أعضاء دخلوا في 20 ثانية، يبعت تنبيه في قناة Logs؛ **مش هيعمل Ban أو Kick تلقائيًا**.

## 5) Permissions Panel

اكتب `/permissions` واختار أي Role من القائمة. هتشوف الصلاحيات بتاعته بأسماء الـ Permissions، ومين Enabled ومين Disabled، والتنقل بصفحات. زر **Search Permission** يفتح مربع كتابة؛ اكتب مثلاً `ban_members` أو `manage_roles`، وهتلاقي كل الرولات اللي عندها الصلاحية دي بشكل مباشر أو عن طريق Administrator.

**مهم:** المعروض هو صلاحيات الـ Role الأساسية على مستوى السيرفر. الصلاحيات الفعلية لعضو ممكن تختلف بسبب رولات تانية أو Channel Overrides.

## 6) ملاحظات

- البوت مش هيقدر يعمل Moderation لعضو أعلى منه أو أعلى من الشخص اللي استخدم الأمر.
- صلاحيات البوت مش المفروض تكون Administrator إلا لو عندك سبب حقيقي.
- ده **بوت شغال بالكود بعد ربطه وتشغيله**؛ مش موقع Dashboard خارجي، ومش Bot مستضاف عند Discord تلقائيًا.
- اختبر الحماية على سيرفر خاص الأول؛ thresholds قابلة للتعديل من ملف `sentinel/guard.py`.
- لو قفلت البرنامج، البوت هيقف. التشغيل الدائم يحتاج جهاز شغال طول الوقت أو VPS/Hosting.

المشروع فيه ملف `README.md` بالإنجليزي، وملفات Docker للتشغيل على استضافة تدعم Docker.

## 7) نشره على Railway (مع حفظ البيانات)

1. افتح Railway واعمل New Project ثم Deploy from GitHub Repo واختار Safehuardbot-.
2. المشروع فيه Dockerfile بالفعل؛ مش محتاج Public Domain أو Web Port.
3. من خدمة Railway افتح Volumes واعمل Add Volume بمسار /app/data.
4. من Variables أضف: DISCORD_TOKEN (توكن جديد) وDEV_GUILD_ID (اختياري) وSENTINEL_DB_PATH=/app/data/sentinel.sqlite3.
5. استخدم Replicas = 1 لأن نسخة المشروع بتستعمل SQLite ووصلة Discord واحدة.
6. راقب Deployment Logs وتأكد إن البوت سجل Logged in as وظهرت أوامر Slash.

حماية البيانات: تشغيل Railway من غير Volume، أو حفظ قاعدة البيانات خارجه، هيتوقف برسالة واضحة بدل فقدان الإعدادات عند إعادة النشر.

الأمان: اعمل Reset لتوكن Discord وألغِ GitHub PAT القديم اللي اتشارك؛ متضيفش GitHub PAT لخدمة Railway.

## 8) اختبار المشروع

بعد تثبيت المكتبات شغّل:

    python -m unittest discover -s tests -v

GitHub Actions بيشغّل Compile وTests على Python 3.12 مع كل Push أو Pull Request.
اختبارات Discord هي Mock Tests من غير اتصال بسيرفر حقيقي؛ جرّب Kick وBan وTimeout وPermissions على Test Server قبل الاستخدام الفعلي.

## 9) التشغيل على Botkeep / Pterodactyl

- وصل السيرفر بمستودع GitHub على فرع `main`، وحدد ملف التشغيل `main.py`.
- `DISCORD_TOKEN` لازم يحتوي على التوكن الجديد. `DEV_GUILD_ID` اختياري.
- على Botkeep مش محتاج متغيرات Railway؛ `RAILWAY_ENVIRONMENT` و`RAILWAY_SERVICE_ID` مش لازم يكونوا موجودين.
- `SENTINEL_DB_PATH` اختياري: لو مش موجود، ملف SQLite هيتعمل باسم `sentinel.sqlite3` في مجلد المشروع.
- لو حابب مسار واضح: `SENTINEL_DB_PATH=/home/container/data/sentinel.sqlite3` (المجلد بيتعمل تلقائيًا).
- تأكد من لوحة الاستضافة إن مساحة ملفات السيرفر دائمة واعمل Backup دوري لملف SQLite؛ الكود وحده مش بيضمن بقاء البيانات بعد إعادة تثبيت أو حذف السيرفر.
- رسالة `PyNaCl is not installed` مجرد تحذير متعلق بالصوت، ومش تمنع تشغيل بوت الإدارة النصي.
- بعد تحديث الملفات شغّل Restart، ولو حصل Error جديد راجع Console وابعت traceback من غير أي Tokens.

## 10) اللوحات الجديدة + العربية + الاختصارات

بعد تحديث Botkeep من GitHub وإعادة تشغيل البوت، جرّب:
- `/helpbot`: لوحة رئيسية بأزرار لعرض الإدارة والحماية والرولات والاختصارات واللغة.
- `/permissions`: مستكشف صلاحيات الرولات بتصميم جديد، اختيار رول، بحث وتنقل بين الصفحات.
- `/guard status`: لوحة حالة الحماية بثلاث مؤشرات وتفاصيل قناة اللوج.
- `/language`: لوحة اختيار اللغة (English / العربية) للسيرفر بالكامل. تغيير اللغة يحتاج Manage Server.

### اختصارات من غير / ولا Prefix

الاختصارات مش مفعلة من نفسها، وبتشتغل بس في قناة الإدارة اللي انت بتحددها:
1. اعمل قناة للإدارة مثل #staff-commands وخلي الوصول ليها للمشرفين فقط.
2. نفذ `/shortcut channel channel:#staff-commands` لتحديد قناة التنفيذ.
3. نفذ `/shortcut set word:اص action:timeout` لإنشاء الاختصار.
4. اعمل Reply على رسالة عضو في نفس القناة واكتب `اص 10` لعمل Timeout عشر دقائق.
5. أو اكتب `اص @member 10` (باستخدام Mention فعلي من Discord).
6. نفذ `/shortcut list` لمراجعة الاختصارات و`/shortcut remove word:اص` للحذف.
7. `/shortcut disable` لإيقاف اختصارات الرسائل مع الاحتفاظ بأسمائها.

الأوامر المتاحة للاختصارات: `timeout`, `untimeout`, `kick`, `ban`, `purge`, `antispam_on`, `antispam_off`, `links_on`, `links_off`, `raid_on`, `raid_off`.

مثال مسح: اربط `مسح` بـ `purge`، واكتب `مسح 5` في قناة الإدارة.

**أمان مهم:** لازم Message Content Intent يكون مفعّل من Discord Developer Portal. أي رسالة شبه الاختصار لكن مختلفة مش هتتنفذ. محدش يقدر ينفذ Shortcut من غير صلاحية Discord المناسبة أو على شخص أعلى منه في ترتيب الرولات. ينصح باستخدام قناة Staff خاصة لأن أوامر Ban/Kick حساسة، وعدم اختيار كلمات شائعة في الشات العادي.

الإعدادات الجديدة بتتحفظ في نفس ملف SQLite وبتترحل تلقائيًا من قاعدة البيانات القديمة من غير مسح إعدادات الحماية. خُد نسخة احتياطية قبل التحديث خصوصًا لو بتستخدم بيانات حقيقية.

## 11) الاختصارات في كل القنوات + Mute

**الوضع الافتراضي الجديد:** الاختصارات المسجلة بتشتغل في **أي قناة نصية داخل السيرفر** البوت يقدر يشوفها ويرد فيها، طالما المستخدم يمتلك الصلاحيات المطلوبة. أوامر Slash كمان مش مقيدة بقناة محددة من كود البوت.

- `/shortcut anywhere` يرجع الاختصارات للعمل في كل القنوات، ويلغي أي تقييد قديم.
- `/shortcut channel channel:#staff-commands` يقيّد الاختصارات بالقناة المحددة فقط.
- `/shortcut disable` يوقف الاختصارات مؤقتًا من غير ما يحذفها؛ `/shortcut anywhere` يرجعها.
- `/shortcut diagnose` يعرض إعدادات الاختصارات وحالتها في القناة الحالية.
- `/shortcut list` يعرض الاختصارات المسجلة.

أوامر الميوت:
- `/mute member:@user minutes:10` يعمل **Text Mute** باستخدام Discord Timeout (منع الكتابة والتفاعل لفترة).
- `/unmute member:@user` يلغي Text Mute / Timeout.
- `/vmute member:@user` يعمل **Voice Mute** للعضو الموجود في روم صوتي (Mute Members).
- `/vunmute member:@user` يلغي Voice Mute.

ممكن تعمل `/shortcut set word:اص action:mute` وبعدها في أي قناة تكتب `اص @user 10` أو ترد على رسالة العضو وتكتب `اص 10`. وللصوت، اعمل اختصار مختلف زي `سك` وربطه بـ `vmute`.

**مهم:** لازم يكون Message Content Intent مفعل، ورول البوت أعلى من رول العضو المستهدف. لا تستخدم اختصارات شائعة جدًا ممكن تظهر بالصدفة في المحادثات. لو كنت مقيّد الاختصارات بقناة في الإصدار السابق، نفذ `/shortcut anywhere` مرة واحدة لإلغاء التقييد. قواعد البيانات القديمة بتترحل تلقائيًا مع الحفاظ على الاختصارات.

**لو أمر مش بينفذ:** جرب `/shortcut diagnose` وراجع Console في Botkeep. لازم الاختصار يكون متسجل بـ `/shortcut set`، والعضو يتحدد بـ Mention أو Reply، وتكون صلاحيات الإدارة مناسبة.
