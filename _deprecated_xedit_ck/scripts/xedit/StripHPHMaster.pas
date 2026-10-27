{
  StripHPHMaster.pas
  -------------------
  Run AFTER FaceGen has been baked for the follower (core/facegen_bridge.py /
  the "2. Generate FaceGen" button) -- NOT before, or CK will have baked the
  low-poly vanilla head instead of the high-poly one.

  Removes any live HeadParts references on every NPC_ record in the target
  plugin that resolve into a file named "HighPolyHead*", then runs xEdit's
  built-in Clean Masters so HighPolyHead.esm/.esp drops off the plugin's
  master list if nothing else in it still needs it.

  Why this is safe: Skyrim renders an NPC's face from the baked FaceGen head
  mesh/texture (the .nif/.dds pair under meshes|textures/actors/character/
  FaceGenData/...), not from a live lookup of the HeadParts list at runtime.
  The live reference is only needed to RE-bake FaceGen later. Once baked, it's
  safe to drop.

  Run via:
    SSEEdit.exe -autoexit -autoload -script:"StripHPHMaster.pas" -D:"<DataPath>"
  Reads "follower_params.txt" (needs just NEW_PLUGIN=) and writes
  "follower_strip_result.txt", both next to this script.
}
unit StripHPHMaster;

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

function StripHighPolyHeadReferences(npc: IInterface): integer;
var
  headParts, entry, resolved, ownerFile: IInterface;
  i, removed: integer;
  ownerName: string;
begin
  removed := 0;
  headParts := ElementByName(npc, 'Head Parts');
  if not Assigned(headParts) then begin
    Result := 0;
    Exit;
  end;

  for i := ElementCount(headParts) - 1 downto 0 do begin
    entry := ElementByIndex(headParts, i);
    resolved := LinksTo(entry);
    if not Assigned(resolved) then
      Continue;

    ownerFile := GetFile(resolved);
    if not Assigned(ownerFile) then
      Continue;

    ownerName := GetFileName(ownerFile);
    if Pos('highpolyhead', LowerCase(ownerName)) > 0 then begin
      RemoveElement(headParts, entry);
      Inc(removed);
    end;
  end;

  Result := removed;
end;

function Initialize: integer;
var
  params: TStrings;
  scriptDir, pluginName: string;
  targetFile: IwbFile;
  grp: IInterface;
  rec: IInterface;
  i, totalStripped, npcCount: integer;
begin
  Result := 0;
  scriptDir := ExtractFilePath(ParamStr(0));
  ParamsPath := scriptDir + 'follower_params.txt';
  ResultPath := scriptDir + 'follower_strip_result.txt';

  if not FileExists(ParamsPath) then begin
    AddMessage('StripHPHMaster: no follower_params.txt found -- aborting.');
    Exit;
  end;

  params := TStringList.Create;
  try
    params.LoadFromFile(ParamsPath);
    pluginName := ReadParam(params, 'NEW_PLUGIN', '');

    if pluginName = '' then begin
      WriteResult(false, 'NEW_PLUGIN missing from follower_params.txt.');
      Exit;
    end;

    targetFile := FileByName(pluginName);
    if not Assigned(targetFile) then begin
      WriteResult(false, 'Plugin "' + pluginName + '" is not loaded in this xEdit session.');
      Exit;
    end;

    grp := GroupBySignature(targetFile, 'NPC_');
    totalStripped := 0;
    npcCount := 0;

    if Assigned(grp) then begin
      for i := 0 to ElementCount(grp) - 1 do begin
        rec := ElementByIndex(grp, i);
        Inc(npcCount);
        totalStripped := totalStripped + StripHighPolyHeadReferences(rec);
      end;
    end;

    if totalStripped > 0 then begin
      CleanMasters(targetFile);
      WriteResult(true, 'Checked ' + IntToStr(npcCount) + ' NPC record(s) in ' + pluginName +
        ', removed ' + IntToStr(totalStripped) + ' live High Poly Head reference(s), and cleaned masters. ' +
        'If nothing else in the plugin needs it, HighPolyHead should no longer appear as a master.');
    end else begin
      WriteResult(true, 'Checked ' + IntToStr(npcCount) + ' NPC record(s) in ' + pluginName +
        ' -- no live High Poly Head references found (nothing to strip, or it wasn''t used).');
    end;
  finally
    params.Free;
  end;
end;

end.
