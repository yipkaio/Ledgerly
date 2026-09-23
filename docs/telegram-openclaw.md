# Telegram receipt intake with OpenClaw

A bot response of `AUTO_FILED` is an internal classification outcome, not a
human approval or bank payment. `REVIEW_QUEUE` is a successful upload that
still needs a reviewer decision in the web workspace. The
[user guide](user-guide.md#telegram-examples) illustrates both outcomes.

This integration adds a private Telegram receipt entry point without creating a second accounting pipeline. OpenClaw receives one authorized user's attachment, and the `ledgerly-receipt` skill sends it to the existing authenticated `POST /receipts/upload` endpoint on localhost. Ledgerly remains responsible for validation, OCR, extraction, vendor lookup, classification, confidence gating, persistence, duplicates, and review routing.

The organiser's [ShowMeYourAgent starter kit](https://github.com/kenken64/ShowMeYourAgent-Starter-Kit#install-and-configure-openclaw) is the base host-install reference. The files under `integrations/openclaw/` are the Ledgerly-specific layer.

## Security boundary

- Use a dedicated Telegram bot and one numeric Telegram user ID.
- Direct messages use an explicit allowlist; Telegram groups are disabled.
- OpenClaw and Ledgerly communicate over `http://127.0.0.1:8000` only.
- The bridge accepts only regular JPEG, PNG, or PDF files inside OpenClaw's inbound-media directories. It rejects URLs, relative paths, traversal, symlinks, bad signatures, and oversized files.
- The shared application key is exposed only to the OpenClaw Gateway process. It is never put in the skill, Telegram messages, logs, or Git.
- The bridge returns a bounded summary and omits raw OCR text, local paths, and secrets.
- `AUTO_FILED` means the confidence gate accepted the classification. `REVIEW_QUEUE` is pending human review, not approval.

OpenClaw has real host access. Keep the Gateway bound to localhost, install only reviewed skills, and do not enable broad Telegram users, groups, or arbitrary shell instructions.

## 1. Prepare Ledgerly

Use `AUTH_MODE=hybrid` if Firebase protects the web UI, or `AUTH_MODE=api_key` for the current MVP. In either mode, OpenClaw uses the same `APP_API_KEY` as a trusted service integration.

Confirm the container is private and healthy:

```bash
cd ~/expense-classification-agent
docker compose up -d --build --wait --wait-timeout 300
curl --fail http://127.0.0.1:8000/health
```

The Compose port mapping must remain `127.0.0.1:8000:8000`; do not expose port 8000 publicly.

## 2. Install OpenClaw on Lightsail

Follow the organiser guide on the same Ubuntu 24.04 Lightsail instance. Its current sequence installs OpenCode, NVM/Node 24, OpenClaw, then runs:

```bash
openclaw onboard
```

Keep the Gateway service on its default loopback listener (`127.0.0.1:18789`). Complete the organiser-provided model gateway configuration during onboarding. That model powers OpenClaw's routing; it does not replace Ledgerly's OCR or classification agents.

## 3. Create the Telegram bot

1. In Telegram, open the verified `@BotFather` account.
2. Run `/newbot`, choose a name and username, and copy the token.
3. On Lightsail, store it in a regular file:

```bash
install -d -m 700 ~/.openclaw/secrets
read -rsp 'Telegram bot token: ' TELEGRAM_TOKEN_INPUT; echo
printf '%s' "$TELEGRAM_TOKEN_INPUT" > ~/.openclaw/secrets/telegram-bot-token
unset TELEGRAM_TOKEN_INPUT
chmod 600 ~/.openclaw/secrets/telegram-bot-token
```

Never paste the token into chat, source control, screenshots, or command history.

## 4. Install the Ledgerly skill

From the checked-out Ledgerly repository:

```bash
bash integrations/openclaw/install.sh
openclaw skills list
```

Confirm `ledgerly-receipt` is present. OpenClaw normally watches skills; start a new chat with `/new` or restart the Gateway if an existing session does not see it.

## 5. Supply the integration key to systemd

Create a root-readable environment file without printing the key:

```bash
sudo install -d -m 700 /etc/openclaw
read -rsp 'Ledgerly APP_API_KEY: ' LEDGERLY_KEY_INPUT; echo
printf 'LEDGERLY_API_KEY=%s\nLEDGERLY_API_URL=http://127.0.0.1:8000\n' "$LEDGERLY_KEY_INPUT" \
  | sudo tee /etc/openclaw/ledgerly.env >/dev/null
unset LEDGERLY_KEY_INPUT
sudo chmod 600 /etc/openclaw/ledgerly.env
sudo systemctl edit openclaw-gateway
```

Add this systemd override:

```ini
[Service]
EnvironmentFile=/etc/openclaw/ledgerly.env
```

Then reload and restart:

```bash
sudo systemctl daemon-reload
sudo systemctl restart openclaw-gateway
sudo systemctl status openclaw-gateway --no-pager
```

If the organiser installation uses a user service, run the equivalent `systemctl --user edit/restart` commands and store the environment file under a user-owned `0700` directory instead.

## 6. Lock Telegram to your account

First use pairing only to learn and approve your own account. Add the following temporary Telegram block to `~/.openclaw/openclaw.json` while preserving the provider/model configuration created during onboarding:

```json5
channels: {
  telegram: {
    enabled: true,
    tokenFile: "/home/ubuntu/.openclaw/secrets/telegram-bot-token",
    dmPolicy: "pairing",
    groupPolicy: "disabled",
  },
},
```

Then verify the channel:

```bash
openclaw channels status --probe
```

Send any DM to the bot, then:

```bash
openclaw pairing list telegram
openclaw pairing approve telegram <PAIRING_CODE>
```

Record your numeric Telegram user ID from the pairing output or `openclaw logs --follow`. Merge `integrations/openclaw/openclaw.example.json5` into `~/.openclaw/openclaw.json`, replacing the user-ID placeholder. Preserve the working provider/model sections created during onboarding.

The final Telegram policy must be:

```json5
dmPolicy: "allowlist",
allowFrom: ["YOUR_NUMERIC_TELEGRAM_USER_ID"],
groupPolicy: "disabled",
configWrites: false,
```

Validate and restart:

```bash
openclaw doctor
sudo systemctl restart openclaw-gateway
openclaw channels status --probe
```

## 7. Test end to end

Send one disposable receipt image to the bot with: `Upload this receipt`.

Expected reply fields:

- receipt ID
- vendor and date
- total and currency
- category and confidence
- `AUTO_FILED` or `REVIEW_QUEUE`

Confirm the same receipt appears in the Ledgerly web UI. For a review-queue result, verify it appears under Pending reviews. Then test these fail-closed cases:

1. Send a text-only request: the bot should ask for one attachment.
2. Send two attachments: the bot should ask for exactly one.
3. Send a non-receipt file type: the bridge should reject it.
4. Message the bot from a different Telegram account: it should receive no Ledgerly access.
5. Upload the same file again: the bot should report a duplicate and the existing receipt ID, without creating a second record.

Inspect status without leaking message bodies or secrets:

```bash
openclaw channels status --probe
openclaw hooks list
sudo journalctl -u openclaw-gateway -n 100 --no-pager
docker compose logs --tail=100 api
```

Do not paste complete logs into public channels; receipt metadata can be sensitive.

## Rollback

Disable the Telegram channel or the skill, then restart the Gateway. Ledgerly's web workflow continues unchanged.

```bash
openclaw config set channels.telegram.enabled false --strict-json
sudo systemctl restart openclaw-gateway
```
