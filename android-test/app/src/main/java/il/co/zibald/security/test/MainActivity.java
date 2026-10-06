package il.co.zibald.security.test;
import android.Manifest;import android.app.*;import android.os.*;import android.webkit.*;import android.content.pm.PackageManager;import android.net.Uri;import android.provider.Settings;import android.content.Intent;import android.view.*;import android.widget.*;
public class MainActivity extends Activity{
 WebView w; final String URL="https://employee-time-tracker-pwa-test-production.up.railway.app/";
 @Override public void onCreate(Bundle b){super.onCreate(b);w=new WebView(this);setContentView(w);WebSettings s=w.getSettings();s.setJavaScriptEnabled(true);s.setDomStorageEnabled(true);s.setMediaPlaybackRequiresUserGesture(false);w.setWebViewClient(new WebViewClient());w.setWebChromeClient(new WebChromeClient(){@Override public void onPermissionRequest(PermissionRequest r){runOnUiThread(()->r.grant(r.getResources()));}@Override public boolean onShowFileChooser(WebView v,ValueCallback<Uri[]> cb,FileChooserParams p){try{startActivityForResult(p.createIntent(),42);fileCb=cb;return true;}catch(Exception e){return false;}}});if(Build.VERSION.SDK_INT>=23)requestPermissions(new String[]{Manifest.permission.CAMERA,Manifest.permission.ACCESS_FINE_LOCATION,Manifest.permission.ACCESS_COARSE_LOCATION},7);w.loadUrl(URL);}
 ValueCallback<Uri[]> fileCb;@Override protected void onActivityResult(int r,int c,Intent d){super.onActivityResult(r,c,d);if(r==42&&fileCb!=null){fileCb.onReceiveValue(FileChooserParams.parseResult(c,d));fileCb=null;}}
 @Override public void onBackPressed(){if(w.canGoBack())w.goBack();else super.onBackPressed();}
}
