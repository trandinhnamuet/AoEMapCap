package io.github.trandinhnamuet.aoemapcap;

import android.app.Activity;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.net.Uri;
import android.os.Bundle;
import android.view.WindowManager;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import androidx.webkit.WebViewAssetLoader;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;

/**
 * Trang mobile/web (đóng gói trong assets) chạy trong WebView ở https://appassets.androidplatform.net/app/.
 *
 * Máy chủ AoE-MapCap trên máy tính chỉ có http trong mạng nhà, nên trang không gọi thẳng nó (mixed content, CORS):
 * trang gọi /pc/&lt;ip:cổng&gt;/&lt;mã&gt;/... cùng nguồn, app tự tải http://&lt;ip:cổng&gt;/&lt;mã&gt;/... rồi trả về.
 */
public class MainActivity extends Activity {
    private static final String HOST = "appassets.androidplatform.net";
    private static final String START = "https://" + HOST + "/app/index.html";

    private WebView web;
    private WebViewAssetLoader assets;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        WebView.setWebContentsDebuggingEnabled((getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0);

        web = new WebView(this);
        web.setBackgroundColor(0xFF0F1114);
        setContentView(web);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);

        assets = new WebViewAssetLoader.Builder()
                .setDomain(HOST)
                .addPathHandler("/app/", new WebViewAssetLoader.AssetsPathHandler(this))
                .build();
        web.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest req) {
                Uri u = req.getUrl();
                if (!HOST.equals(u.getHost())) return null;
                String path = u.getEncodedPath();
                if (path != null && path.startsWith("/pc/")) return proxy(u, req.getMethod());
                return assets.shouldInterceptRequest(u);
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                Uri u = req.getUrl();
                if (HOST.equals(u.getHost())) return false;
                // liên kết ngoài mở bằng trình duyệt
                try { startActivity(new Intent(Intent.ACTION_VIEW, u)); } catch (Exception ignored) { }
                return true;
            }
        });

        if (state == null || web.restoreState(state) == null) web.loadUrl(START);
    }

    private static WebResourceResponse proxy(Uri u, String method) {
        if (!"GET".equals(method)) return error(405, "Method Not Allowed", "chỉ hỗ trợ GET");
        String query = u.getEncodedQuery();
        String target = "http://" + u.getEncodedPath().substring(4) + (query != null ? "?" + query : "");
        try {
            HttpURLConnection c = (HttpURLConnection) new URL(target).openConnection();
            c.setConnectTimeout(5000);
            c.setReadTimeout(60000);
            c.setInstanceFollowRedirects(false);
            c.setRequestProperty("Accept-Encoding", "identity");    // để Content-Length đúng cho thanh tiến độ
            int code = c.getResponseCode();
            if (code < 200 || (code >= 300 && code < 400)) {
                c.disconnect();
                return error(502, "Bad Gateway", "máy tính trả mã " + code);
            }
            InputStream in = code >= 400 ? c.getErrorStream() : c.getInputStream();
            if (in == null) in = new ByteArrayInputStream(new byte[0]);
            String type = c.getContentType();
            String mime = type == null ? "application/octet-stream" : type.split(";")[0].trim();
            Map<String, String> headers = new HashMap<>();
            long len = c.getContentLengthLong();
            if (len >= 0) headers.put("Content-Length", Long.toString(len));
            headers.put("Cache-Control", "no-store");
            String reason = c.getResponseMessage();
            if (reason == null || reason.isEmpty()) reason = code >= 400 ? "Error" : "OK";
            return new WebResourceResponse(mime, null, code, reason, headers, in);
        } catch (IOException | IllegalArgumentException e) {
            return error(502, "Bad Gateway", "không kết nối được máy tính: " + e.getMessage());
        }
    }

    private static WebResourceResponse error(int code, String reason, String text) {
        return new WebResourceResponse("text/plain", "utf-8", code, reason, new HashMap<>(),
                new ByteArrayInputStream(text.getBytes(StandardCharsets.UTF_8)));
    }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        web.saveState(out);
    }

    @Override
    protected void onPause() {
        web.onPause();
        super.onPause();
    }

    @Override
    protected void onResume() {
        super.onResume();
        web.onResume();
    }

    @Override
    protected void onDestroy() {
        web.destroy();
        super.onDestroy();
    }
}
