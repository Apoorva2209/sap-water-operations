package app.sap.water

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Color
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity

/**
 * Thin Android client for the SAP edge controller.
 *
 * The decision engine, safety logic and event log run on the controller
 * (Raspberry Pi or laptop on the farm Wi-Fi, started with SAP_HOST=0.0.0.0 sap-server).
 * This app stores the controller's address and shows its dashboard full-screen.
 * No water decision is made on the phone.
 */
class MainActivity : AppCompatActivity() {

    private val prefs by lazy { getSharedPreferences("sap", Context.MODE_PRIVATE) }
    private lateinit var root: FrameLayout
    private var web: WebView? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        root = FrameLayout(this)
        setContentView(root)
        val saved = prefs.getString("controller", null)
        if (saved.isNullOrBlank()) showSetup() else showDashboard(saved)
    }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    // ---- setup screen ----
    private fun showSetup(error: String? = null) {
        web = null
        root.removeAllViews()
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setPadding(dp(24), dp(24), dp(24), dp(24))
            setBackgroundColor(Color.parseColor("#F4F7FB"))
        }
        col.addView(TextView(this).apply {
            text = "SAP Water"
            textSize = 28f
            setTextColor(Color.parseColor("#0B1F3A"))
        })
        col.addView(TextView(this).apply {
            text = "Enter the controller address shown when you start sap-server, for example 192.168.1.20:8080. Phone and controller must be on the same Wi-Fi."
            setPadding(0, dp(12), 0, dp(16))
        })
        val input = EditText(this).apply {
            hint = "192.168.1.20:8080"
            setText(prefs.getString("controller", ""))
            setSingleLine()
            imeOptions = EditorInfo.IME_ACTION_GO
        }
        col.addView(input, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        val err = TextView(this).apply {
            setTextColor(Color.parseColor("#B3261E"))
            text = error ?: ""
            visibility = if (error == null) View.GONE else View.VISIBLE
        }
        col.addView(err)
        val go = Button(this).apply { text = "Connect" }
        col.addView(go)
        fun connect() {
            val addr = normalize(input.text.toString())
            if (addr == null) {
                err.text = "Enter a valid address, e.g. 192.168.1.20:8080"
                err.visibility = View.VISIBLE
                return
            }
            prefs.edit().putString("controller", addr).apply()
            showDashboard(addr)
        }
        go.setOnClickListener { connect() }
        input.setOnEditorActionListener { _, _, _ -> connect(); true }
        root.addView(col)
    }

    /** Accepts host, host:port or http://host:port. Only plain http on the local network is supported. */
    private fun normalize(raw: String): String? {
        var s = raw.trim().removePrefix("http://").trimEnd('/')
        if (s.isEmpty() || s.contains("://") || s.contains(" ") || s.contains("/")) return null
        if (!s.contains(":")) s += ":8080"
        val port = s.substringAfterLast(":").toIntOrNull() ?: return null
        if (port !in 1..65535) return null
        return s
    }

    // ---- dashboard ----
    @SuppressLint("SetJavaScriptEnabled")
    private fun showDashboard(addr: String) {
        root.removeAllViews()
        val status = TextView(this).apply {
            setPadding(dp(16), dp(16), dp(16), dp(16))
            gravity = Gravity.CENTER
            visibility = View.GONE
        }
        val w = WebView(this).apply {
            settings.javaScriptEnabled = true     // the dashboard is a JavaScript single page
            settings.domStorageEnabled = true
            settings.allowFileAccess = false
            settings.allowContentAccess = false
            webViewClient = object : WebViewClient() {
                // never navigate away from the controller
                override fun shouldOverrideUrlLoading(v: WebView, r: WebResourceRequest): Boolean =
                    r.url.authority != addr

                override fun onPageFinished(v: WebView, url: String) {
                    status.visibility = View.GONE
                }

                override fun onReceivedError(v: WebView, r: WebResourceRequest, e: WebResourceError) {
                    if (r.isForMainFrame) {
                        status.text = "Cannot reach the controller at $addr.\nCheck Wi-Fi and that sap-server is running with SAP_HOST=0.0.0.0.\nTap to retry."
                        status.visibility = View.VISIBLE
                    }
                }
            }
            loadUrl("http://$addr/")
        }
        web = w
        status.setOnClickListener { status.visibility = View.GONE; w.loadUrl("http://$addr/") }
        val bar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setBackgroundColor(Color.parseColor("#0B1F3A"))
            setPadding(dp(12), dp(4), dp(12), dp(4))
            gravity = Gravity.CENTER_VERTICAL
        }
        bar.addView(TextView(this).apply {
            text = "SAP · $addr"
            setTextColor(Color.WHITE)
        }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        bar.addView(Button(this).apply {
            text = "Refresh"
            setOnClickListener { status.visibility = View.GONE; w.reload() }
        })
        bar.addView(Button(this).apply {
            text = "Change"
            setOnClickListener { confirmChange() }
        })
        val col = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        col.addView(bar)
        col.addView(status)
        col.addView(w, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        root.addView(col)
    }

    private fun confirmChange() {
        AlertDialog.Builder(this)
            .setTitle("Change controller?")
            .setMessage("You will be asked for a new address.")
            .setPositiveButton("Change") { _, _ -> showSetup() }
            .setNegativeButton("Cancel", null)
            .show()
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        val w = web
        if (w != null && w.canGoBack()) w.goBack() else super.onBackPressed()
    }
}
