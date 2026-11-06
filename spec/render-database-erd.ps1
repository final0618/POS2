$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

$width = 1960
$height = 1390
$bitmap = [System.Drawing.Bitmap]::new($width, $height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::ClearTypeGridFit

$background = [System.Drawing.Color]::FromArgb(248, 246, 239)
$ink = [System.Drawing.Color]::FromArgb(41, 39, 36)
$muted = [System.Drawing.Color]::FromArgb(112, 105, 96)
$line = [System.Drawing.Color]::FromArgb(222, 216, 205)
$red = [System.Drawing.Color]::FromArgb(199, 44, 49)
$teal = [System.Drawing.Color]::FromArgb(40, 105, 99)
$yellow = [System.Drawing.Color]::FromArgb(231, 184, 64)
$white = [System.Drawing.Color]::White
$graphics.Clear($background)

$titleFont = [System.Drawing.Font]::new('Segoe UI', 30, [System.Drawing.FontStyle]::Bold)
$subtitleFont = [System.Drawing.Font]::new('Segoe UI', 14)
$headerFont = [System.Drawing.Font]::new('Segoe UI', 19, [System.Drawing.FontStyle]::Bold)
$columnFont = [System.Drawing.Font]::new('Segoe UI', 10, [System.Drawing.FontStyle]::Bold)
$fieldFont = [System.Drawing.Font]::new('Segoe UI', 13, [System.Drawing.FontStyle]::Bold)
$typeFont = [System.Drawing.Font]::new('Segoe UI', 12, [System.Drawing.FontStyle]::Bold)
$noteFont = [System.Drawing.Font]::new('Segoe UI', 11)
$footerFont = [System.Drawing.Font]::new('Segoe UI', 12)
$inkBrush = [System.Drawing.SolidBrush]::new($ink)
$mutedBrush = [System.Drawing.SolidBrush]::new($muted)
$whiteBrush = [System.Drawing.SolidBrush]::new($white)
$redBrush = [System.Drawing.SolidBrush]::new($red)
$tealBrush = [System.Drawing.SolidBrush]::new($teal)
$yellowBrush = [System.Drawing.SolidBrush]::new($yellow)
$linePen = [System.Drawing.Pen]::new($line, 1)
$relationPen = [System.Drawing.Pen]::new($teal, 4)

$graphics.DrawString('Good Morning Club | Database ER Diagram', $titleFont, $inkBrush, 58, 38)
$graphics.DrawString('SQLite: data/pos.db    |    4 entities    |    Money stored as INTEGER NTD', $subtitleFont, $mutedBrush, 62, 91)

$menuRows = @(
    @{ Key='PK'; Field='id'; Type='TEXT'; Note='Product identifier' },
    @{ Key=''; Field='name'; Type='TEXT'; Note='Product name' },
    @{ Key=''; Field='category'; Type='TEXT'; Note='Menu category' },
    @{ Key=''; Field='description'; Type='TEXT'; Note='Product description' },
    @{ Key=''; Field='price'; Type='INTEGER'; Note='Price in NTD; >= 0' },
    @{ Key=''; Field='badge'; Type='TEXT'; Note='Menu badge' },
    @{ Key=''; Field='image_url'; Type='TEXT'; Note='Product image URL' },
    @{ Key=''; Field='alt_text'; Type='TEXT'; Note='Image alternative text' },
    @{ Key=''; Field='is_available'; Type='INTEGER'; Note='Availability flag: 0 or 1' }
)
$orderRows = @(
    @{ Key='PK'; Field='id'; Type='TEXT'; Note='Server-generated order ID' },
    @{ Key=''; Field='table_number'; Type='TEXT'; Note='Dining table: 01-12' },
    @{ Key=''; Field='status'; Type='TEXT'; Note='received / preparing / ready / completed / cancelled' },
    @{ Key=''; Field='payment_status'; Type='TEXT'; Note='unpaid / paid / refunded' },
    @{ Key=''; Field='total_amount'; Type='INTEGER'; Note='Order total in NTD' },
    @{ Key=''; Field='created_at'; Type='TEXT'; Note='UTC ISO 8601 timestamp' }
)
$itemRows = @(
    @{ Key='PK/FK'; Field='order_id'; Type='TEXT'; Note='FK -> orders.id; cascade delete' },
    @{ Key='PK/FK'; Field='menu_item_id'; Type='TEXT'; Note='FK -> menu_items.id; restrict delete' },
    @{ Key=''; Field='item_name'; Type='TEXT'; Note='Name snapshot at order time' },
    @{ Key=''; Field='unit_price'; Type='INTEGER'; Note='Price snapshot in NTD' },
    @{ Key=''; Field='quantity'; Type='INTEGER'; Note='Quantity; > 0' },
    @{ Key=''; Field='subtotal'; Type='INTEGER'; Note='unit_price * quantity' }
)
$inputRows = @(
    @{ Key='PK'; Field='id'; Type='INTEGER'; Note='Auto increment' },
    @{ Key=''; Field='input_text'; Type='TEXT'; Note='User text' },
    @{ Key=''; Field='created_at'; Type='TEXT'; Note='UTC timestamp' }
)

function Draw-Entity($X, $Y, $Width, $Name, $Rows, $Accent, $RowHeight) {
    $cardHeight = 78 + ($Rows.Count * $RowHeight) + 10
    $shadowBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(26, 30, 25, 20))
    $cardBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::White)
    $accentBrush = [System.Drawing.SolidBrush]::new($Accent)
    $graphics.FillRectangle($shadowBrush, $X + 5, $Y + 6, $Width, $cardHeight)
    $graphics.FillRectangle($cardBrush, $X, $Y, $Width, $cardHeight)
    $graphics.DrawRectangle($linePen, $X, $Y, $Width, $cardHeight)
    $graphics.FillRectangle($accentBrush, $X, $Y, $Width, 58)
    $graphics.DrawString($Name, $headerFont, $whiteBrush, $X + 20, $Y + 13)

    if ($Width -lt 500) {
        $keyX = $X + 15; $fieldX = $X + 88; $typeX = $X + 215; $noteX = $X + 295
    }
    else {
        $keyX = $X + 20; $fieldX = $X + 92; $typeX = $X + 258; $noteX = $X + 360
    }
    $columnY = $Y + 67
    $graphics.DrawString('KEY', $columnFont, $mutedBrush, $keyX, $columnY)
    $graphics.DrawString('FIELD', $columnFont, $mutedBrush, $fieldX, $columnY)
    $graphics.DrawString('TYPE', $columnFont, $mutedBrush, $typeX, $columnY)
    $graphics.DrawString('DESCRIPTION', $columnFont, $mutedBrush, $noteX, $columnY)

    $startY = $Y + 88
    for ($index = 0; $index -lt $Rows.Count; $index++) {
        $rowY = $startY + ($index * $RowHeight)
        $graphics.DrawLine($linePen, $X + 16, $rowY - 5, $X + $Width - 16, $rowY - 5)
        if ($Rows[$index].Key) {
            $keyBrush = if ($Rows[$index].Key -eq 'PK') { $redBrush } else { $tealBrush }
            $graphics.DrawString($Rows[$index].Key, $columnFont, $keyBrush, $keyX, $rowY + 4)
        }
        $graphics.DrawString($Rows[$index].Field, $fieldFont, $inkBrush, $fieldX, $rowY + 1)
        $graphics.DrawString($Rows[$index].Type, $typeFont, $tealBrush, $typeX, $rowY + 3)
        $graphics.DrawString($Rows[$index].Note, $noteFont, $mutedBrush, $noteX, $rowY + 4)
    }
    $shadowBrush.Dispose(); $cardBrush.Dispose(); $accentBrush.Dispose()
}

$graphics.DrawLine($relationPen, 905, 520, 850, 790)
$graphics.DrawString('1', $fieldFont, $tealBrush, 890, 500)
$graphics.DrawString('0..N', $fieldFont, $tealBrush, 815, 760)
$graphics.DrawString('menu item appears in order lines', $noteFont, $tealBrush, 865, 638)
$graphics.DrawLine($relationPen, 1450, 535, 1320, 790)
$graphics.DrawString('1', $fieldFont, $tealBrush, 1450, 515)
$graphics.DrawString('1..N', $fieldFont, $tealBrush, 1300, 760)
$graphics.DrawString('order contains line items', $noteFont, $tealBrush, 1360, 648)

Draw-Entity 55 170 850 'menu_items | Menu' $menuRows $red 42
Draw-Entity 1120 170 790 'orders | Order header' $orderRows $teal 42
Draw-Entity 530 790 890 'order_items | Order lines' $itemRows $yellow 42
Draw-Entity 1490 800 420 'inputs | Input log' $inputRows $red 47

$graphics.DrawLine($linePen, 58, 1270, 1900, 1270)
$graphics.DrawString('PK = primary key    |    FK = foreign key    |    order_items uses composite PK (order_id, menu_item_id)', $footerFont, $inkBrush, 62, 1285)
$graphics.DrawString('Relationships: menu_items 1 : 0..N order_items    |    orders 1 : 1..N order_items    |    inputs is independent', $footerFont, $mutedBrush, 62, 1315)

$output = Join-Path $PSScriptRoot 'database-erd.jpg'
$bitmap.Save($output, [System.Drawing.Imaging.ImageFormat]::Jpeg)
$graphics.Dispose(); $bitmap.Dispose()
$titleFont.Dispose(); $subtitleFont.Dispose(); $headerFont.Dispose(); $columnFont.Dispose(); $fieldFont.Dispose(); $typeFont.Dispose(); $noteFont.Dispose(); $footerFont.Dispose()
$inkBrush.Dispose(); $mutedBrush.Dispose(); $whiteBrush.Dispose(); $redBrush.Dispose(); $tealBrush.Dispose(); $yellowBrush.Dispose(); $linePen.Dispose(); $relationPen.Dispose()
Get-Item $output | Select-Object FullName, Length
