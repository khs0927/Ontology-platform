$py=$args
$src='D:\AECData\artifacts\doc_e6b4f051105f7af3792f2bc5\rev-0\converted\'+(Get-ChildItem 'D:\AECData\artifacts\doc_e6b4f051105f7af3792f2bc5\rev-0\converted\' -Filter *.dxf)[0].Name
$t='C:\CODE\zium-templates\autocad'; $w="$env:TEMP\zdxf"; $s="$env:TEMP\zsmk"
ni -ItemType Directory -Force $t,"$w\o","$s\o",'C:\CODE\zium-templates\smoke' | Out-Null
uv run -q --no-project --with ezdxf python C:\Users\khs09\mkdwt.py $src "$w\ZIUM_template.dxf"
uv run -q --no-project --with ezdxf python C:\Users\khs09\mkdwt.py $src "$s\GOYEON1525_sheet.dxf" smoke
$oda='C:\Program Files\ODA\ODAFileConverter 27.1.0\ODAFileConverter.exe'
& $oda $w "$w\o" ACAD2018 DWG 0 1 "*.DXF" | Out-Null; & $oda $s "$s\o" ACAD2018 DWG 0 1 "*.DXF" | Out-Null
Copy-Item "$w\o\ZIUM_template.dwg" "$t\ZIUM_template.dwt" -Force; Copy-Item "$w\ZIUM_template.dxf" $t -Force
Copy-Item "$s\o\GOYEON1525_sheet.dwg" 'C:\CODE\zium-templates\smoke\' -Force
gci $t,'C:\CODE\zium-templates\smoke' | select FullName,Length | ft -auto | Out-String -Width 200
