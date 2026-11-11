package ai.nova.assistant

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import android.telephony.SmsManager
import org.json.JSONObject

/** Executes the device commands the server sends to this phone. */
class DeviceActions(private val context: Context) {

    fun execute(name: String, cmd: JSONObject): String {
        val action = cmd.optString("action", cmd.optString("name", ""))
        val args = cmd.optJSONObject("args") ?: JSONObject()
        return when (action) {
            "open_app" -> openApp(args.optString("name", args.optString("package", "")))
            "open_url" -> openUrl(args.optString("url", ""))
            "send_message" -> sendSms(
                args.optString("to", ""),
                args.optString("body", args.optString("text", ""))
            )
            "open_settings" -> openSettings()
            "notify", "notification" -> "notifications are shown by the app itself"
            else -> "unsupported on phone: $action"
        }
    }

    private fun openApp(target: String): String {
        if (target.isBlank()) return "no app name given"
        val pm = context.packageManager
        val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        val apps = pm.queryIntentActivities(intent, 0)
        val want = target.lowercase()
        for (info in apps) {
            val label = info.loadLabel(pm).toString()
            if (label.lowercase() == want || label.lowercase().contains(want)) {
                val launch = Intent(Intent.ACTION_MAIN)
                    .addCategory(Intent.CATEGORY_LAUNCHER)
                    .setClassName(info.activityInfo.packageName, info.activityInfo.name)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                context.startActivity(launch)
                return "opened $label"
            }
        }
        return "no app matched '$target'"
    }

    private fun openUrl(url: String): String {
        if (url.isBlank()) return "no url given"
        val fixed = if (url.startsWith("http")) url else "https://$url"
        context.startActivity(
            Intent(Intent.ACTION_VIEW, Uri.parse(fixed))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        )
        return "opened $fixed"
    }

    private fun sendSms(to: String, body: String): String {
        if (to.isBlank() || body.isBlank()) return "need both 'to' and 'body'"
        val sm = SmsManager.getDefault()
        val parts = sm.divideMessage(body)
        sm.sendMultipartTextMessage(to, null, parts, null, null)
        return "sent SMS to $to"
    }

    private fun openSettings(): String {
        context.startActivity(
            Intent(Settings.ACTION_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        )
        return "opened settings"
    }
}
