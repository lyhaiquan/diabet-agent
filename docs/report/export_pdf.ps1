# Mo bao cao bang Word, cap nhat muc luc va so trang, luu lai roi xuat PDF.
#   powershell -ExecutionPolicy Bypass -File tools\export_pdf.ps1 -DocPath <docx> -PdfPath <pdf>
param([string]$DocPath, [string]$PdfPath)
$ErrorActionPreference = 'Stop'
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
    $doc = $word.Documents.Open($DocPath, $false, $false)
    # cap nhat hai lan de so trang trong muc luc on dinh sau khi muc luc dan trang
    for ($k = 0; $k -lt 2; $k++) {
        foreach ($t in $doc.TablesOfContents) { $t.Update() }
        $doc.Fields.Update() | Out-Null
        $doc.Repaginate()
    }
    $doc.Save()
    Write-Output ("pages=" + $doc.ComputeStatistics(2))
    $doc.SaveAs2([ref]$PdfPath, [ref]17)      # 17 = wdFormatPDF
    Write-Output "pdf-ok"
    $doc.Close([ref]0)
}
finally {
    $word.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
}
