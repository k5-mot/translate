param(
    [Parameter(Mandatory = $true)][string]$SourceDocx,
    [Parameter(Mandatory = $true)][string]$DestinationPdf
)

$ErrorActionPreference = 'Stop'
$word = $null
$document = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $word.Options.UpdateFieldsAtPrint = $false
    $word.Options.UpdateLinksAtOpen = $false
    $document = $word.Documents.Open($SourceDocx, $false, $true)
    $document.SaveAs2($DestinationPdf, 17)
}
finally {
    if ($document) {
        $document.Close($false)
        [Runtime.InteropServices.Marshal]::FinalReleaseComObject($document) | Out-Null
    }
    if ($word) {
        $word.Quit()
        [Runtime.InteropServices.Marshal]::FinalReleaseComObject($word) | Out-Null
    }
}
