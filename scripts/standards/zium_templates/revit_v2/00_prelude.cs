// ZIUM_template_v2 build — prelude (runs inside revit_send_code_to_revit; never touches the user's open doc)
var A = app.Application; var L = new System.Text.StringBuilder();
const string P = @"C:\CODE\zium-templates\revit\ZIUM_template_v2.rte";
const string FONT = "나눔스퀘어"; // SIN36 §0: NanumSquare (official Naver, per-user install 2026-10-24)
Document d = null; foreach (Document x in A.Documents) if (x.PathName == P) d = x;
if (d == null) d = A.OpenDocumentFile(P);
void Try(string n, Action a) { try { a(); } catch (Exception ex) { L.AppendLine("  ! " + n + ": " + ex.Message); } }
void Tx(string n, Action a) { using (var t = new Transaction(d, n)) { t.Start(); try { a(); t.Commit(); L.AppendLine("ok " + n); } catch (Exception ex) { t.RollBack(); L.AppendLine("FAIL " + n + ": " + ex); } } }
double F(double mm) => mm / 304.8;
T ByName<T>(string n) where T : Element => new FilteredElementCollector(d).OfClass(typeof(T)).Cast<T>().FirstOrDefault(e => e.Name == n);
ElementType ET(string fam, string n) => new FilteredElementCollector(d).OfClass(typeof(ElementType)).Cast<ElementType>().FirstOrDefault(e => (e.FamilyName ?? "") == fam && e.Name == n);
Color RGB(int r, int g, int b) => new Color((byte)r, (byte)g, (byte)b);
Category LinesCat() => d.Settings.Categories.get_Item(BuiltInCategory.OST_Lines);
Parameter BP(Element e, string[] bips, string[] names) { foreach (var b in bips) { BuiltInParameter bp; if (Enum.TryParse(b, out bp)) { var q = e.get_Parameter(bp); if (q != null) return q; } } foreach (var n in names) { var q = e.LookupParameter(n); if (q != null) return q; } throw new Exception("param not found " + string.Join("/", names)); }
