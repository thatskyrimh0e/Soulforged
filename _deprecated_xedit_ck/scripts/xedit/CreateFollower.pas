{
  CreateFollower.pas
  ------------------
  Driven by Follower Builder (Python/PySide6 app). Reads a small JSON-ish
  parameter file written by the app (see core/xedit_bridge.py) describing the
  new follower, clones a base NPC_ record as a starting point inside a new
  plugin, and applies the requested name/race/sex.

  This script intentionally does NOT attempt FaceGen generation or BodySlide
  batch-building -- those still require Creation Kit / BodySlide directly
  (xEdit has no FaceGen renderer). It also does NOT strip the High Poly Head
  master here -- that has to happen AFTER FaceGen is baked (see
  StripHPHMaster.pas), otherwise CK would bake the low-poly vanilla head
  instead of the high-poly one.

  Run via:
    SSEEdit.exe -autoexit -autoload -script:"CreateFollower.pas" -D:"<DataPath>"
  Params file path is fixed relative to this script's own folder as
  "follower_params.txt" (one KEY=VALUE per line), written fresh by the app
  before each run, and results are written to "follower_result.txt" next to it.
}
unit CreateFollower;

interface
uses xEditAPI;

implementation

var
  ParamsPath, ResultPath: string;

function ReadParam(lines: TStrings; key, default_: string): string;
var
  i: integer;
  line: string;
begin
  Result := default_;
  for i := 0 to lines.Count - 1 do begin
    line := lines[i];
    if Pos(key + '=', line) = 1 then begin
      Result := Copy(line, Length(key) + 2, MaxInt);
      Exit;
    end;
  end;
end;

procedure WriteResult(ok: boolean; msg: string);
var
  f: TStrings;
begin
  f := TStringList.Create;
  try
    f.Add('OK=' + BoolToStr(ok, true));
    f.Add('MESSAGE=' + msg);
    f.SaveToFile(ResultPath);
  finally
    f.Free;
  end;
end;


function TrySetEditValue(rec: IInterface; const paths: array of string; value: string): boolean;
var
  i: integer;
begin
  Result := False;
  for i := Low(paths) to High(paths) do begin
    try
      if SetElementEditValues(rec, paths[i], value) then begin
        Result := True;
        Exit;
      end;
    except
      // try next candidate path
    end;
  end;
end;

procedure SplitStr(const s, sep: string; list: TStrings);
var
  rest: string;
  p: integer;
begin
  list.Clear;
  rest := s;
  if rest = '' then Exit;
  repeat
    p := Pos(sep, rest);
    if p = 0 then begin
      list.Add(rest);
      rest := '';
    end else begin
      list.Add(Copy(rest, 1, p - 1));
      rest := Copy(rest, p + Length(sep), MaxInt);
    end;
  until rest = '';
end;

// Adds one cross-plugin reference to the NPC's "Head Parts" (PNAM) array.
// Returns '' on success, or a short reason string on failure.
function AddHeadPart(npc: IInterface; pluginName, formIdHex: string): string;
var
  srcFile: IwbFile;
  srcRec, container, newElem: IInterface;
begin
  Result := 'plugin "' + pluginName + '" not loaded in this xEdit session';
  srcFile := FileByName(pluginName);
  if not Assigned(srcFile) then Exit;

  Result := 'form ' + formIdHex + ' not found in ' + pluginName;
  srcRec := RecordByFormID(srcFile, StrToInt('$' + formIdHex), true);
  if not Assigned(srcRec) then Exit;

  try
    AddRequiredElementMasters(srcRec, GetFile(npc), False);

    container := ElementByPath(npc, 'Head Parts');
    if not Assigned(container) then
      container := Add(npc, 'Head Parts', True);

    newElem := ElementAssign(container, HighInteger, nil, True);
    SetElementNativeValues(newElem, '', GetLoadOrderFormID(srcRec));
    Result := '';
  except
    on E: Exception do
      Result := 'xEdit error: ' + E.Message;
  end;
end;

// Adds/updates one Tint Layer entry (index + ARGB color) on the NPC.
// Returns '' on success, or a short reason string on failure.
function ApplyTint(npc: IInterface; tintIndex, alpha, red, green, blue: integer): string;
var
  container, newElem: IInterface;
  colorPacked: Cardinal;
begin
  Result := '';
  try
    container := ElementByPath(npc, 'Tint Layers');
    if not Assigned(container) then
      container := Add(npc, 'Tint Layers', True);

    newElem := ElementAssign(container, HighInteger, nil, True);

    if not TrySetEditValue(newElem, ['Tint Layer\Index', 'Index'], IntToStr(tintIndex)) then begin
      Result := 'could not set tint index ' + IntToStr(tintIndex);
      Exit;
    end;

    colorPacked := (Cardinal(alpha) shl 24) or (Cardinal(red) shl 16) or (Cardinal(green) shl 8) or Cardinal(blue);

    // Try a single packed native color value first, then per-channel edit
    // values as a fallback (exact subrecord layout can differ by game/CK
    // version, so both are attempted).
    try
      SetElementNativeValues(newElem, 'Tint Layer\Color', colorPacked);
      Exit;
    except
    end;
    try
      SetElementNativeValues(newElem, 'Color', colorPacked);
      Exit;
    except
    end;

    TrySetEditValue(newElem, ['Tint Layer\Color\Red', 'Color\Red'], IntToStr(red));
    TrySetEditValue(newElem, ['Tint Layer\Color\Green', 'Color\Green'], IntToStr(green));
    TrySetEditValue(newElem, ['Tint Layer\Color\Blue', 'Color\Blue'], IntToStr(blue));
    TrySetEditValue(newElem, ['Tint Layer\Color\Alpha', 'Color\Alpha'], IntToStr(alpha));
  except
    on E: Exception do
      Result := 'xEdit error: ' + E.Message;
  end;
end;

// Applies everything a .jslot export can faithfully provide: head parts
// (hair/brows/eyes/scars/etc.), tint/makeup colors, hair color, and weight.
// NOTE: a .jslot's "morphs" (sculpt-tool vertex deltas / extended SKEE
// sliders) have no native NPC_ record equivalent and are intentionally not
// applied here -- see core/jslot_reader.py for why. warnings is appended
// to with any individual field that couldn't be set, so one bad field
// doesn't block the rest.
procedure ApplyJslotData(npc: IInterface; params: TStrings; warnings: TStrings);
var
  headPartsRaw, tintsRaw, hairColorRaw, weightRaw: string;
  records, fields: TStrings;
  i, partType, tintIndex, alpha, red, green, blue: integer;
  plugin, formHex, err: string;
begin
  headPartsRaw := ReadParam(params, 'JSLOT_HEADPARTS', '');
  tintsRaw     := ReadParam(params, 'JSLOT_TINTS', '');
  hairColorRaw := ReadParam(params, 'JSLOT_HAIRCOLOR', '');
  weightRaw    := ReadParam(params, 'JSLOT_WEIGHT', '');

  records := TStringList.Create;
  fields := TStringList.Create;
  try
    if headPartsRaw <> '' then begin
      SplitStr(headPartsRaw, ';', records);
      for i := 0 to records.Count - 1 do begin
        SplitStr(records[i], '|', fields);
        if fields.Count < 3 then Continue;
        plugin := fields[0];
        formHex := fields[1];
        partType := StrToIntDef(fields[2], -1);
        err := AddHeadPart(npc, plugin, formHex);
        if err <> '' then
          warnings.Add('Head part type ' + IntToStr(partType) + ' (' + plugin + '|' + formHex + '): ' + err);
      end;
    end;

    if tintsRaw <> '' then begin
      SplitStr(tintsRaw, ';', records);
      for i := 0 to records.Count - 1 do begin
        SplitStr(records[i], '|', fields);
        if fields.Count < 5 then Continue;
        tintIndex := StrToIntDef(fields[0], -1);
        alpha := StrToIntDef(fields[1], 255);
        red := StrToIntDef(fields[2], 0);
        green := StrToIntDef(fields[3], 0);
        blue := StrToIntDef(fields[4], 0);
        err := ApplyTint(npc, tintIndex, alpha, red, green, blue);
        if err <> '' then
          warnings.Add('Tint index ' + IntToStr(tintIndex) + ': ' + err);
      end;
    end;

    if hairColorRaw <> '' then begin
      if not TrySetEditValue(npc, ['HCLF', 'Hair Color'], hairColorRaw) then
        if not TrySetEditValue(npc, ['HCLF\FormID'], hairColorRaw) then
          warnings.Add('Could not set hair color -- set it manually in xEdit (HCLF).');
    end;

    if weightRaw <> '' then begin
      if not TrySetEditValue(npc, ['NAM7', 'Weight', 'DNAM\Weight'], weightRaw) then
        warnings.Add('Could not set weight -- set it manually in xEdit.');
    end;
  finally
    records.Free;
    fields.Free;
  end;
end;

function Initialize: integer;
var
  params, warnings, resultLines: TStrings;
  scriptDir, newPluginName, baseEsp, baseFormId, followerName: string;
  raceEdid, sexStr, resultMsg, newFormIdHex: string;
  newFile, baseFile: IwbFile;
  baseNpc, newNpc: IInterface;
begin
  Result := 0;
  scriptDir := ExtractFilePath(ParamStr(0)); // xEdit scripts run from its own Edit Scripts folder
  ParamsPath := scriptDir + 'follower_params.txt';
  ResultPath := scriptDir + 'follower_result.txt';

  if not FileExists(ParamsPath) then begin
    AddMessage('CreateFollower: no follower_params.txt found next to the script -- aborting.');
    Exit;
  end;

  params := TStringList.Create;
  try
    params.LoadFromFile(ParamsPath);

    newPluginName := ReadParam(params, 'NEW_PLUGIN', 'MyFollower.esp');
    baseEsp       := ReadParam(params, 'BASE_PLUGIN', '');
    baseFormId    := ReadParam(params, 'BASE_FORMID', '');   // hex, e.g. 0007647C
    followerName  := ReadParam(params, 'NAME', 'New Follower');
    raceEdid      := ReadParam(params, 'RACE_EDID', 'NordRace');
    sexStr        := ReadParam(params, 'SEX', 'Female');

    if (baseEsp = '') or (baseFormId = '') then begin
      WriteResult(false, 'BASE_PLUGIN and BASE_FORMID are required (pick a donor NPC as a starting template).');
      Exit;
    end;

    baseFile := FileByName(baseEsp);
    if not Assigned(baseFile) then begin
      WriteResult(false, 'Base plugin "' + baseEsp + '" is not loaded in this xEdit session -- add it to the load order.');
      Exit;
    end;

    baseNpc := RecordByFormID(baseFile, StrToInt('$' + baseFormId), true);
    if not Assigned(baseNpc) then begin
      WriteResult(false, 'Could not find NPC_ record ' + baseFormId + ' in ' + baseEsp + '.');
      Exit;
    end;

    // Create (or reuse) the destination plugin as a new ESP.
    newFile := AddNewFileName(newPluginName);
    if not Assigned(newFile) then begin
      WriteResult(false, 'Could not create new plugin ' + newPluginName + '.');
      Exit;
    end;

    // Clone the donor NPC into the new plugin as a fresh record.
    newNpc := wbCopyElementToFile(baseNpc, newFile, true, true);
    if not Assigned(newNpc) then begin
      WriteResult(false, 'Record clone failed.');
      Exit;
    end;

    SetElementEditValues(newNpc, 'FULL', followerName);
    SetElementEditValues(newNpc, 'EDID', StringReplace(followerName, ' ', '', [rfReplaceAll]) + 'NPC');

    // Race (by EDID lookup against the master the base record's race comes from;
    // falls back silently -- leaves donor's race -- if not found, logged below).
    if not SetElementEditValues(newNpc, 'RNAM', raceEdid) then
      AddMessage('CreateFollower: could not set race to "' + raceEdid + '" directly by EDID; leaving donor race. Set it manually in xEdit if needed.');

    if SameText(sexStr, 'Male') then
      SetElementNativeValues(newNpc, 'ACBS - Flags\Female', 0)
    else
      SetElementNativeValues(newNpc, 'ACBS - Flags\Female', 1);

    warnings := TStringList.Create;
    try
      ApplyJslotData(newNpc, params, warnings);

      resultMsg := 'Created ' + followerName + ' in ' + newPluginName +
        '. Next: run "2. Generate FaceGen" in Creation Kit (bakes the high-poly shape), ' +
        'THEN "3. Remove HPH Master" to drop the HighPolyHead dependency.';

      if warnings.Count > 0 then begin
        resultMsg := resultMsg + ' | jslot warnings (' + IntToStr(warnings.Count) + '): ' + warnings.CommaText;
        AddMessage('CreateFollower: jslot warnings: ' + warnings.Text);
      end;

      AddMessage('CreateFollower: created ' + followerName + ' in ' + newPluginName + ' from ' + baseEsp + ':' + baseFormId + '.');

      // The form ID the new NPC got inside its own plugin -- needed by the
      // Python app so it can copy an exported RaceMenu head into the right
      // FaceGenData\...\<formid>.nif / .dds path for this specific record.
      newFormIdHex := IntToHex(FormID(newNpc) and $FFFFFF, 8);

      resultLines := TStringList.Create;
      try
        resultLines.Add('OK=True');
        resultLines.Add('MESSAGE=' + resultMsg);
        resultLines.Add('NEW_FORMID=' + newFormIdHex);
        resultLines.SaveToFile(ResultPath);
      finally
        resultLines.Free;
      end;
    finally
      warnings.Free;
    end;
  finally
    params.Free;
  end;
end;

end.
