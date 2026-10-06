package il.co.mishmaron.app;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.ClipData;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.MediaStore;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.*;
import android.widget.*;
import androidx.core.content.FileProvider;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowInsetsCompat;
import org.json.*;
import java.io.*;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class MainActivity extends Activity {
    static final String REGISTRY = "https://raw.githubusercontent.com/moshe111378-stack/employee-time-tracker/mishmaron-play-all-clients/config/organizations.json";
    static final String PRIVACY = "https://mishmaron-privacy-production.up.railway.app/privacy";
    static final String SUPPORT = "moshe111378@gmail.com";
    static final int NAVY = Color.rgb(7,21,43), GOLD = Color.rgb(217,181,90), LIGHT = Color.rgb(233,239,248);
    static final int FILE_REQUEST = 21, LOCATION_REQUEST = 22, EXPORT_REQUEST = 23;
    final ExecutorService io = Executors.newSingleThreadExecutor();
    final Handler ui = new Handler(Looper.getMainLooper());
    final LinkedHashMap<String, Organization> organizations = new LinkedHashMap<>();
    SharedPreferences prefs;
    LinearLayout root;
    WebView web;
    volatile Organization selected;
    TextView status;
    ProgressBar progress;
    ValueCallback<Uri[]> fileCallback;
    Uri cameraUri;
    String pendingGeoOrigin;
    GeolocationPermissions.Callback pendingGeo;
    String pendingExport;
    String pendingExportCookie;
    volatile int generation;
    boolean switching;

    static final class Organization {
        final String code,name,url;
        Organization(String c,String n,String u){code=c;name=n;url=u;}
    }

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        prefs=getSharedPreferences("mishmaron",MODE_PRIVATE);
        File[] oldPhotos=new File(getCacheDir(),"camera").listFiles();
        if(oldPhotos!=null)for(File photo:oldPhotos)if(photo.isFile())photo.delete();
        CookieManager.getInstance().setAcceptCookie(true);
        try { parseRegistry(readText(getAssets().open("organizations.json"),131072)); }
        catch(Exception e){ /* Error is displayed if no registry is available. */ }
        String cache=prefs.getString("registry",null);
        if(cache!=null)try{parseRegistry(cache);}catch(Exception ignored){}
        Organization remembered=organizations.get(prefs.getString("organization",""));
        if(remembered!=null)openOrganization(remembered);else showChooser();
        updateRegistry();
    }
    int dp(int value){return Math.round(value*getResources().getDisplayMetrics().density);}
    TextView text(String label,int size,int color){TextView t=new TextView(this);t.setText(label);t.setTextSize(size);t.setTextColor(color);t.setPadding(0,dp(7),0,dp(7));return t;}
    GradientDrawable box(int color){GradientDrawable d=new GradientDrawable();d.setColor(color);d.setCornerRadius(dp(16));return d;}
    Button button(String title){Button b=new Button(this);b.setText(title);b.setAllCaps(false);b.setTextSize(17);b.setTextColor(NAVY);b.setBackground(box(GOLD));b.setPadding(dp(14),dp(10),dp(14),dp(10));LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,dp(56));p.setMargins(0,dp(8),0,dp(8));b.setLayoutParams(p);return b;}
    void newRoot(){
        root=new LinearLayout(this);root.setOrientation(LinearLayout.VERTICAL);root.setBackgroundColor(NAVY);root.setLayoutDirection(View.LAYOUT_DIRECTION_RTL);
        setContentView(root);
        ViewCompat.setOnApplyWindowInsetsListener(root,(v,w)->{Insets in=w.getInsets(WindowInsetsCompat.Type.systemBars()|WindowInsetsCompat.Type.ime());v.setPadding(in.left,in.top,in.right,in.bottom);return w;});
        ViewCompat.requestApplyInsets(root);
    }
    void parseRegistry(String json)throws JSONException{
        JSONObject object=new JSONObject(json);
        if(object.getInt("version")!=1)throw new JSONException("Unsupported registry");
        JSONArray array=object.getJSONArray("organizations");
        if(array.length()<1||array.length()>500)throw new JSONException("Invalid size");
        LinkedHashMap<String,Organization> next=new LinkedHashMap<>();
        for(int i=0;i<array.length();i++){
            JSONObject row=array.getJSONObject(i);String code=row.getString("code"),name=row.getString("name"),url=row.getString("url");
            if(!code.matches("[A-Za-z0-9_-]{1,32}")||name.trim().isEmpty()||name.length()>100||!UrlPolicy.organizationRoot(url)||next.containsKey(code))throw new JSONException("Invalid organization");
            next.put(code,new Organization(code,name,url));
        }
        organizations.clear();organizations.putAll(next);
    }
    void updateRegistry(){io.execute(()->{
        try{
            HttpURLConnection c=(HttpURLConnection)new URL(REGISTRY).openConnection();c.setConnectTimeout(10000);c.setReadTimeout(10000);c.setInstanceFollowRedirects(false);
            String json;try{if(c.getResponseCode()!=200)return;json=readText(c.getInputStream(),131072);}finally{c.disconnect();}
            ui.post(()->{if(isFinishing()||isDestroyed())return;try{parseRegistry(json);prefs.edit().putString("registry",json).apply();}catch(Exception ignored){}});
        }catch(Exception ignored){ /* Bundled or last-known registry remains usable offline. */ }
    });}
    void showChooser(){
        generation++;selected=null;newRoot();
        ScrollView scroll=new ScrollView(this);root.addView(scroll,new LinearLayout.LayoutParams(-1,-1));
        LinearLayout page=new LinearLayout(this);page.setOrientation(LinearLayout.VERTICAL);page.setPadding(dp(24),dp(30),dp(24),dp(24));scroll.addView(page);
        ImageView logo=new ImageView(this);logo.setImageResource(R.drawable.brand_logo);logo.setContentDescription("משמרון");logo.setAdjustViewBounds(true);page.addView(logo,new LinearLayout.LayoutParams(-1,dp(150)));
        TextView brand=text("משמרון",40,GOLD);brand.setTypeface(null,Typeface.BOLD);page.addView(brand);
        page.addView(text("העבודה שלך. במקום אחד.",21,LIGHT));
        page.addView(text("כניסה לאזור האישי",21,LIGHT));
        page.addView(text("בהפעלה הראשונה הזינו את קוד הארגון שקיבלתם מהמנהל. לאחר ההתחברות האפליקציה תיפתח ישירות באזור שלכם.",16,LIGHT));
        EditText code=new EditText(this);code.setSingleLine(true);code.setHint("קוד הארגון");code.setTextColor(LIGHT);code.setHintTextColor(Color.LTGRAY);code.setContentDescription("קוד ארגון");page.addView(code);
        Button join=button("כניסה עם קוד");page.addView(join);join.setOnClickListener(v->{Organization org=organizations.get(code.getText().toString().trim());if(org==null)new AlertDialog.Builder(this).setMessage("הקוד לא נמצא. בדקו את הקוד שקיבלתם מהמנהל וחיבור לאינטרנט, ואז פתחו מחדש את המסך.").setPositiveButton("הבנתי",null).show();else openOrganization(org);});
        Button privacy=button("פרטיות ומחיקת מידע");page.addView(privacy);privacy.setOnClickListener(v->privacy());
        TextView note=text("כל ארגון מנהל את העובדים והנתונים שלו. בחירת ארגון אינה מעניקה הרשאות ניהול.",13,Color.LTGRAY);page.addView(note);
    }
    void openOrganization(Organization org){
        if(switching)return;switching=true;generation++;
        // Preserve the existing login only for the exact same organization and origin.
        cancelPending();
        if(web!=null){web.stopLoading();web.clearHistory();web.clearCache(true);web.destroy();web=null;}
        if(org.code.equals(prefs.getString("organization",""))&&org.url.equals(prefs.getString("organizationUrl",""))){switching=false;selected=org;buildWeb();return;}
        WebStorage.getInstance().deleteAllData();GeolocationPermissions.getInstance().clearAll();
        CookieManager.getInstance().removeAllCookies(done->{CookieManager.getInstance().flush();switching=false;if(isFinishing()||isDestroyed())return;selected=org;prefs.edit().putString("organization",org.code).putString("organizationUrl",org.url).remove("startPath").apply();buildWeb();});
    }
    void buildWeb(){
        newRoot();
        LinearLayout bar=new LinearLayout(this);bar.setGravity(Gravity.CENTER_VERTICAL);bar.setPadding(dp(12),dp(4),dp(12),dp(4));root.addView(bar);
        ImageView brandIcon=new ImageView(this);brandIcon.setImageResource(R.drawable.brand_logo);brandIcon.setContentDescription("משמרון");bar.addView(brandIcon,new LinearLayout.LayoutParams(dp(40),dp(40)));
        status=text(selected.name,17,GOLD);status.setTypeface(null,Typeface.BOLD);bar.addView(status,new LinearLayout.LayoutParams(0,-2,1));
        Button menu=new Button(this);menu.setText("תפריט");bar.addView(menu);menu.setOnClickListener(v->new AlertDialog.Builder(this).setItems(new String[]{"רענון","החלפת ארגון","פרטיות ומחיקת מידע","פנייה לתמיכה"},(d,i)->{if(i==0)web.reload();if(i==1)confirmSwitch();if(i==2)privacy();if(i==3)contact();}).show());
        progress=new ProgressBar(this,null,android.R.attr.progressBarStyleHorizontal);progress.setMax(100);root.addView(progress,new LinearLayout.LayoutParams(-1,dp(3)));
        web=new WebView(this);root.addView(web,new LinearLayout.LayoutParams(-1,0,1));
        WebSettings s=web.getSettings();s.setJavaScriptEnabled(true);s.setDomStorageEnabled(true);s.setGeolocationEnabled(true);
        s.setAllowFileAccess(false);s.setAllowContentAccess(true);s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);s.setSupportMultipleWindows(false);s.setJavaScriptCanOpenWindowsAutomatically(false);s.setSafeBrowsingEnabled(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web,false);
        web.setWebViewClient(new WebViewClient(){
            @Override public boolean shouldOverrideUrlLoading(WebView view,WebResourceRequest r){if(allowed(r.getUrl().toString()))return false;if(r.isForMainFrame()&&r.hasGesture())external(r.getUrl());return true;}
            @Override public WebResourceResponse shouldInterceptRequest(WebView view,WebResourceRequest r){String u=r.getUrl().toString();if(allowed(u)&&"/__mishmaron_native_brand_v2.png".equals(r.getUrl().getPath()))return new WebResourceResponse("image/png",null,getResources().openRawResource(R.raw.brand_logo));if(allowed(u))return null;return new WebResourceResponse("text/plain","UTF-8",403,"Blocked",Collections.emptyMap(),new ByteArrayInputStream(new byte[0]));}
            @Override public void onReceivedSslError(WebView view,SslErrorHandler handler,SslError error){handler.cancel();ui.post(()->connectionError("לא ניתן לאמת חיבור מאובטח לארגון."));}
            @Override public void onReceivedError(WebView view,WebResourceRequest r,WebResourceError e){if(r.isForMainFrame())connectionError("לא ניתן להתחבר. בדקו את החיבור לאינטרנט ונסו לרענן.");}
            @Override public void onPageFinished(WebView view,String url){
                CookieManager.getInstance().flush();
                if(!allowed(url))return;
                String path=Uri.parse(url).getPath();
                if(path!=null&&path.startsWith("/admin"))prefs.edit().putString("startPath",path.equals("/admin/login")||path.equals("/admin/logout")?"/":"/admin").apply();
                else if("/".equals(path))prefs.edit().putString("startPath","/").apply();
                applyAppPresentation(view);
            }
        });
        web.setWebChromeClient(new WebChromeClient(){
            @Override public void onProgressChanged(WebView view,int p){progress.setProgress(p);progress.setVisibility(p==100?View.GONE:View.VISIBLE);}
            @Override public void onGeolocationPermissionsShowPrompt(String origin,GeolocationPermissions.Callback callback){location(origin,callback);}
            @Override public void onGeolocationPermissionsHidePrompt(){if(pendingGeo!=null){pendingGeo.invoke(pendingGeoOrigin,false,false);pendingGeo=null;}}
            @Override public void onPermissionRequest(PermissionRequest request){request.deny();}
            @Override public boolean onShowFileChooser(WebView v,ValueCallback<Uri[]> cb,FileChooserParams p){
                if(!allowed(v.getUrl()))return false;if(fileCallback!=null)fileCallback.onReceiveValue(null);fileCallback=cb;
                new AlertDialog.Builder(MainActivity.this).setTitle("תמונה לדיווח נוכחות").setMessage("התמונה שתבחרו או תצלמו תישלח לארגון ותישמר עם דיווח הנוכחות. היא תהיה זמינה למנהלים המורשים.").setPositiveButton("צילום תמונה",(d,i)->takePhoto()).setNeutralButton("בחירת תמונה",(d,i)->pickPhoto()).setNegativeButton("ביטול",(d,i)->finishFile(null)).setOnCancelListener(d->finishFile(null)).show();return true;
            }
        });
        web.setDownloadListener((url,agent,disposition,type,length)->export(url));
        String start=prefs.getString("startPath","/");
        web.loadUrl(selected.url+("/admin".equals(start)?"admin":""));
    }
    void applyAppPresentation(WebView view){
        // Only runs on the selected organization. Does not grant or bypass server authentication.
        try{
            String script=readText(getAssets().open("app-presentation.js"),32768);
            view.evaluateJavascript(script,null);
        }catch(IOException ignored){}
    }
    boolean allowed(String url){return selected!=null&&UrlPolicy.sameOrigin(selected.url,url);}
    void connectionError(String message){if(isFinishing()||web==null)return;status.setText("אין חיבור · "+selected.name);new AlertDialog.Builder(this).setMessage(message).setPositiveButton("רענון",(d,i)->web.reload()).setNegativeButton("סגירה",null).show();}
    void external(Uri uri){String scheme=uri.getScheme();if(!"https".equals(scheme)&&!"mailto".equals(scheme)&&!"tel".equals(scheme))return;new AlertDialog.Builder(this).setMessage("לפתוח מחוץ למשמרון?").setPositiveButton("פתיחה",(d,i)->{try{startActivity(new Intent(Intent.ACTION_VIEW,uri));}catch(Exception e){Toast.makeText(this,"אין יישום מתאים לפתיחת הקישור",Toast.LENGTH_SHORT).show();}}).setNegativeButton("ביטול",null).show();}
    void confirmSwitch(){new AlertDialog.Builder(this).setTitle("החלפת ארגון").setMessage("החלפת ארגון תנתק את החיבור במכשיר הזה. הנתונים בארגון יישמרו.").setPositiveButton("החלפת ארגון",(d,i)->{generation++;cancelPending();prefs.edit().remove("organization").remove("organizationUrl").remove("startPath").apply();if(web!=null){web.stopLoading();web.clearCache(true);web.destroy();web=null;}WebStorage.getInstance().deleteAllData();CookieManager.getInstance().removeAllCookies(v->{CookieManager.getInstance().flush();if(!isFinishing())showChooser();});}).setNegativeButton("ביטול",null).show();}
    void location(String origin,GeolocationPermissions.Callback cb){
        if(!allowed(origin)){cb.invoke(origin,false,false);return;}
        if(pendingGeo!=null)pendingGeo.invoke(pendingGeoOrigin,false,false);
        pendingGeo=cb;pendingGeoOrigin=origin;
        new AlertDialog.Builder(this).setTitle("מיקום בעת דיווח נוכחות").setMessage("משמרון תשלח לארגון את מיקום המכשיר בעת דיווח כניסה או יציאה ותשמור אותו עם הדיווח לצורך אימות נוכחות. אין איסוף מיקום ברקע. ללא אישור מיקום לא ניתן להשלים דיווח הדורש אותו.").setPositiveButton("המשך",(d,i)->{if(checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)==PackageManager.PERMISSION_GRANTED||checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION)==PackageManager.PERMISSION_GRANTED)finishGeo(true);else requestPermissions(new String[]{Manifest.permission.ACCESS_FINE_LOCATION,Manifest.permission.ACCESS_COARSE_LOCATION},LOCATION_REQUEST);}).setNegativeButton("לא עכשיו",(d,i)->finishGeo(false)).setOnCancelListener(d->finishGeo(false)).show();
    }
    void finishGeo(boolean allow){if(pendingGeo!=null){pendingGeo.invoke(pendingGeoOrigin,allow&&allowed(pendingGeoOrigin),false);pendingGeo=null;pendingGeoOrigin=null;}}
    @Override public void onRequestPermissionsResult(int request,String[] permissions,int[] grants){super.onRequestPermissionsResult(request,permissions,grants);if(request==LOCATION_REQUEST)finishGeo(checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)==PackageManager.PERMISSION_GRANTED||checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION)==PackageManager.PERMISSION_GRANTED);}
    void takePhoto(){try{File dir=new File(getCacheDir(),"camera");if(!dir.exists()&&!dir.mkdirs())throw new IOException();File photo=File.createTempFile("attendance-",".jpg",dir);cameraUri=FileProvider.getUriForFile(this,getPackageName()+".files",photo);Intent camera=new Intent(MediaStore.ACTION_IMAGE_CAPTURE);camera.putExtra(MediaStore.EXTRA_OUTPUT,cameraUri);camera.setClipData(ClipData.newRawUri("photo",cameraUri));camera.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION|Intent.FLAG_GRANT_READ_URI_PERMISSION);startActivityForResult(camera,FILE_REQUEST);}catch(Exception e){cameraUri=null;finishFile(null);Toast.makeText(this,"לא ניתן לפתוח מצלמה. נסו לבחור תמונה.",Toast.LENGTH_LONG).show();}}
    void pickPhoto(){cameraUri=null;Intent pick=new Intent(Intent.ACTION_OPEN_DOCUMENT);pick.setType("image/*");pick.addCategory(Intent.CATEGORY_OPENABLE);try{startActivityForResult(pick,FILE_REQUEST);}catch(Exception e){finishFile(null);}}
    void finishFile(Uri[] uris){if(fileCallback!=null){fileCallback.onReceiveValue(uris);fileCallback=null;}}
    void export(String url){if(!allowed(url))return;pendingExport=url;pendingExportCookie=CookieManager.getInstance().getCookie(url);Intent save=new Intent(Intent.ACTION_CREATE_DOCUMENT);save.setType("application/vnd.ms-excel");save.addCategory(Intent.CATEGORY_OPENABLE);save.putExtra(Intent.EXTRA_TITLE,"mishmaron-report.xls");try{startActivityForResult(save,EXPORT_REQUEST);}catch(Exception e){pendingExport=null;pendingExportCookie=null;Toast.makeText(this,"לא ניתן לפתוח שמירת קובץ",Toast.LENGTH_SHORT).show();}}
    @Override protected void onActivityResult(int request,int result,Intent data){super.onActivityResult(request,result,data);
        if(request==FILE_REQUEST){Uri u=null;if(result==RESULT_OK){u=cameraUri!=null?cameraUri:(data==null?null:data.getData());if(u!=null&&!"content".equals(u.getScheme()))u=null;}finishFile(u==null?null:new Uri[]{u});cameraUri=null;}
        if(request==EXPORT_REQUEST){String url=pendingExport,cookie=pendingExportCookie;pendingExport=null;pendingExportCookie=null;if(result==RESULT_OK&&data!=null&&data.getData()!=null&&allowed(url))saveExport(url,cookie,data.getData(),generation);}
    }
    void saveExport(String url,String cookie,Uri dest,int epoch){io.execute(()->{try{if(epoch!=generation)return;HttpURLConnection c=(HttpURLConnection)new URL(url).openConnection();c.setConnectTimeout(15000);c.setReadTimeout(15000);c.setInstanceFollowRedirects(false);if(cookie!=null)c.setRequestProperty("Cookie",cookie);try{if(c.getResponseCode()!=200||c.getContentType()==null||!c.getContentType().toLowerCase(Locale.ROOT).contains("application/vnd.ms-excel"))throw new IOException();try(InputStream input=c.getInputStream();OutputStream output=getContentResolver().openOutputStream(dest)){byte[] buffer=new byte[8192];int count,total=0;while((count=input.read(buffer))!=-1){if(epoch!=generation||((total+=count)>20*1024*1024))throw new IOException();output.write(buffer,0,count);}}}finally{c.disconnect();}ui.post(()->Toast.makeText(this,"הדוח נשמר",Toast.LENGTH_LONG).show());}catch(Exception e){ui.post(()->Toast.makeText(this,"הדוח לא נשמר. נסו שוב לאחר התחברות.",Toast.LENGTH_LONG).show());}});}
    void privacy(){new AlertDialog.Builder(this).setTitle("פרטיות ומחיקת מידע").setMessage("משמרון מנהלת נוכחות ומשמרות עבור הארגון שבחרתם. שמות, טלפונים, מזהי משתמש, דיווחי שעות ושכר, תמונות ומיקום בעת דיווח נשמרים לצורך תפעול המערכת ואימות הנוכחות ונגישים למנהלים המורשים. התקשורת באפליקציה מוצפנת. אין פרסומות או כלי אנליטיקה באפליקציית האנדרואיד.\n\nלמחיקה או תיקון פנו למנהל הארגון או ל־"+SUPPORT+" עם שם הארגון ושם המשתמש. אין לשלוח סיסמה. מידע שחובה לשמור עשוי להישמר לפי דרישות הארגון והדין. מחיקת האפליקציה אינה מוחקת דיווחים בשרת.").setPositiveButton("פנייה בנוגע למידע",(d,i)->contact()).setNeutralButton("מדיניות מלאה",(d,i)->external(Uri.parse(PRIVACY))).setNegativeButton("סגירה",null).show();}
    void contact(){Intent mail=new Intent(Intent.ACTION_SENDTO,Uri.parse("mailto:"+SUPPORT));mail.putExtra(Intent.EXTRA_SUBJECT,"משמרון — פנייה לתמיכה / בקשת מחיקת מידע");try{startActivity(mail);}catch(Exception e){new AlertDialog.Builder(this).setMessage("כתובת התמיכה: "+SUPPORT).setPositiveButton("סגירה",null).show();}}
    void cancelPending(){finishGeo(false);finishFile(null);pendingExport=null;pendingExportCookie=null;cameraUri=null;}
    @Override public void onBackPressed(){if(web!=null&&web.canGoBack())web.goBack();else super.onBackPressed();}
    @Override protected void onDestroy(){generation++;cancelPending();if(web!=null){web.destroy();web=null;}io.shutdownNow();super.onDestroy();}
    static String readText(InputStream input,int limit)throws IOException{try(InputStream in=input;ByteArrayOutputStream out=new ByteArrayOutputStream()){byte[] b=new byte[4096];int n;while((n=in.read(b))!=-1){if(out.size()+n>limit)throw new IOException("Too large");out.write(b,0,n);}return out.toString(StandardCharsets.UTF_8.name());}}
}
