// consolepi-discover-iconpack packs PNG icon variants into ICNS and ICO files.
package main

import (
	"encoding/binary"
	"fmt"
	"os"
	"path/filepath"
)

type iconVariant struct {
	name  string
	chunk string
}

func main() {
	if len(os.Args) != 4 && len(os.Args) != 5 {
		fmt.Fprintln(os.Stderr, "usage: consolepi-discover-iconpack ICONSET ICNS ICO [WINDOWS_SYsO]")
		os.Exit(64)
	}
	iconset, icnsPath, icoPath := os.Args[1], os.Args[2], os.Args[3]
	variants := []iconVariant{
		{"icon_16x16.png", "icp4"},
		{"icon_32x32.png", "icp5"},
		{"icon_32x32@2x.png", "icp6"},
		{"icon_128x128.png", "ic07"},
		{"icon_256x256.png", "ic08"},
		{"icon_512x512.png", "ic09"},
		{"icon_512x512@2x.png", "ic10"},
	}

	chunks := make([][]byte, 0, len(variants))
	total := 8
	for _, variant := range variants {
		png, err := os.ReadFile(filepath.Join(iconset, variant.name))
		if err != nil {
			fatal(err)
		}
		chunk := make([]byte, 8+len(png))
		copy(chunk[:4], variant.chunk)
		binary.BigEndian.PutUint32(chunk[4:8], uint32(len(chunk)))
		copy(chunk[8:], png)
		chunks = append(chunks, chunk)
		total += len(chunk)
	}
	icns := make([]byte, 8, total)
	copy(icns[:4], "icns")
	binary.BigEndian.PutUint32(icns[4:8], uint32(total))
	for _, chunk := range chunks {
		icns = append(icns, chunk...)
	}
	if err := os.WriteFile(icnsPath, icns, 0644); err != nil {
		fatal(err)
	}

	png, err := os.ReadFile(filepath.Join(iconset, "icon_256x256.png"))
	if err != nil {
		fatal(err)
	}
	ico := make([]byte, 0, 22+len(png))
	ico = appendLE16(ico, 0)
	ico = appendLE16(ico, 1)
	ico = appendLE16(ico, 1)
	ico = append(ico, 0, 0, 0, 0) // 256x256, default palette
	ico = appendLE16(ico, 1)
	ico = appendLE16(ico, 32)
	ico = appendLE32(ico, uint32(len(png)))
	ico = appendLE32(ico, 22)
	ico = append(ico, png...)
	if err := os.WriteFile(icoPath, ico, 0644); err != nil {
		fatal(err)
	}
	if len(os.Args) == 5 {
		if err := writeWindowsResource(png, os.Args[4]); err != nil {
			fatal(err)
		}
	}
}

// writeWindowsResource creates a minimal AMD64 COFF .rsrc object containing
// one PNG-backed icon. Go includes a matching *_windows_amd64.syso object in
// the final PE executable without requiring a Windows resource compiler.
func writeWindowsResource(png []byte, path string) error {
	const (
		rootDirectory      = 0
		iconTypeDirectory  = 32
		iconNameDirectory  = 56
		iconLangDirectory  = 80
		iconDataEntry      = 104
		groupTypeDirectory = 120
		groupNameDirectory = 144
		groupLangDirectory = 168
		groupDataEntry     = 192
		resourceData       = 208
		resourceDirectory  = 0x80000000
	)
	groupData := align4(resourceData + len(png))
	resources := make([]byte, groupData+20)
	writeDirectory := func(offset int, entries [][2]uint32) {
		binary.LittleEndian.PutUint16(resources[offset+14:offset+16], uint16(len(entries)))
		for index, entry := range entries {
			position := offset + 16 + index*8
			binary.LittleEndian.PutUint32(resources[position:position+4], entry[0])
			binary.LittleEndian.PutUint32(resources[position+4:position+8], entry[1])
		}
	}
	writeDirectory(rootDirectory, [][2]uint32{{3, resourceDirectory | iconTypeDirectory}, {14, resourceDirectory | groupTypeDirectory}})
	writeDirectory(iconTypeDirectory, [][2]uint32{{1, resourceDirectory | iconNameDirectory}})
	writeDirectory(iconNameDirectory, [][2]uint32{{0x409, resourceDirectory | iconLangDirectory}})
	writeDirectory(iconLangDirectory, [][2]uint32{{0x409, iconDataEntry}})
	writeDirectory(groupTypeDirectory, [][2]uint32{{1, resourceDirectory | groupNameDirectory}})
	writeDirectory(groupNameDirectory, [][2]uint32{{0x409, resourceDirectory | groupLangDirectory}})
	writeDirectory(groupLangDirectory, [][2]uint32{{0x409, groupDataEntry}})
	binary.LittleEndian.PutUint32(resources[iconDataEntry:iconDataEntry+4], resourceData)
	binary.LittleEndian.PutUint32(resources[iconDataEntry+4:iconDataEntry+8], uint32(len(png)))
	binary.LittleEndian.PutUint32(resources[groupDataEntry:groupDataEntry+4], uint32(groupData))
	binary.LittleEndian.PutUint32(resources[groupDataEntry+4:groupDataEntry+8], 20)
	copy(resources[resourceData:], png)
	binary.LittleEndian.PutUint16(resources[groupData:groupData+2], 0)
	binary.LittleEndian.PutUint16(resources[groupData+2:groupData+4], 1)
	binary.LittleEndian.PutUint16(resources[groupData+4:groupData+6], 1)
	binary.LittleEndian.PutUint16(resources[groupData+10:groupData+12], 1)
	binary.LittleEndian.PutUint16(resources[groupData+12:groupData+14], 32)
	binary.LittleEndian.PutUint32(resources[groupData+14:groupData+18], uint32(len(png)))
	binary.LittleEndian.PutUint16(resources[groupData+18:groupData+20], 1)

	rawSize := align4(len(resources))
	const sectionHeaderOffset = 20
	const rawOffset = sectionHeaderOffset + 40
	relocationOffset := rawOffset + rawSize
	symbolOffset := relocationOffset + 20
	coff := make([]byte, symbolOffset+36+4)
	binary.LittleEndian.PutUint16(coff[0:2], 0x8664)
	binary.LittleEndian.PutUint16(coff[2:4], 1)
	binary.LittleEndian.PutUint32(coff[8:12], uint32(symbolOffset))
	binary.LittleEndian.PutUint32(coff[12:16], 2)
	copy(coff[sectionHeaderOffset:sectionHeaderOffset+8], ".rsrc")
	binary.LittleEndian.PutUint32(coff[sectionHeaderOffset+8:sectionHeaderOffset+12], uint32(len(resources)))
	binary.LittleEndian.PutUint32(coff[sectionHeaderOffset+16:sectionHeaderOffset+20], uint32(rawSize))
	binary.LittleEndian.PutUint32(coff[sectionHeaderOffset+20:sectionHeaderOffset+24], rawOffset)
	binary.LittleEndian.PutUint32(coff[sectionHeaderOffset+24:sectionHeaderOffset+28], uint32(relocationOffset))
	binary.LittleEndian.PutUint16(coff[sectionHeaderOffset+32:sectionHeaderOffset+34], 2)
	binary.LittleEndian.PutUint32(coff[sectionHeaderOffset+36:sectionHeaderOffset+40], 0x40000040)
	copy(coff[rawOffset:rawOffset+len(resources)], resources)
	for index, offset := range []int{iconDataEntry, groupDataEntry} {
		position := relocationOffset + index*10
		binary.LittleEndian.PutUint32(coff[position:position+4], uint32(offset))
		binary.LittleEndian.PutUint32(coff[position+4:position+8], 0)
		binary.LittleEndian.PutUint16(coff[position+8:position+10], 3) // IMAGE_REL_AMD64_ADDR32NB
	}
	copy(coff[symbolOffset:symbolOffset+8], ".rsrc")
	binary.LittleEndian.PutUint16(coff[symbolOffset+12:symbolOffset+14], 1)
	coff[symbolOffset+16] = 3 // IMAGE_SYM_CLASS_STATIC
	coff[symbolOffset+17] = 1
	binary.LittleEndian.PutUint32(coff[symbolOffset+18:symbolOffset+22], uint32(rawSize))
	binary.LittleEndian.PutUint16(coff[symbolOffset+22:symbolOffset+24], 2)
	binary.LittleEndian.PutUint32(coff[symbolOffset+36:symbolOffset+40], 4)
	return os.WriteFile(path, coff, 0644)
}

func align4(value int) int { return (value + 3) &^ 3 }

func appendLE16(data []byte, value uint16) []byte {
	return append(data, byte(value), byte(value>>8))
}

func appendLE32(data []byte, value uint32) []byte {
	return append(data, byte(value), byte(value>>8), byte(value>>16), byte(value>>24))
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, "consolepi-discover-iconpack:", err)
	os.Exit(1)
}
