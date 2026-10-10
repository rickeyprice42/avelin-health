import fs from "node:fs";

const source = fs.readFileSync(new URL("./nutrition_bookmarklet.js", import.meta.url), "utf8");
const start = source.indexOf("  const clean=");
const end = source.indexOf("  const fromText=");
if (start < 0 || end < 0 || end <= start) throw new Error("Parser core not found");
const core = source.slice(start, end);

const tests = String.raw`
const assert=(condition,message)=>{if(!condition)throw new Error(message);};
const textNode=value=>({nodeType:3,nodeValue:value});
const element=(tag,...children)=>({nodeType:1,tagName:tag,childNodes:children});
const detached=element("DIV",element("DIV",textNode("Пищевая ценность в 100 г")),element("DIV",textNode("Ккал")),element("DIV",textNode("151.8")));
assert(/Ккал\s*\n\s*151\.8/.test(nodeText(detached)),"Detached DOM text lost row boundaries: "+JSON.stringify(nodeText(detached)));
const inlineNutrition=element("DIV",element("SPAN",textNode("Пищевая ценность в 100 г")),element("SPAN",textNode("Ккал")),element("SPAN",textNode("Белки")),element("SPAN",textNode("Жиры")),element("SPAN",textNode("Углеводы")),element("SPAN",textNode("330")),element("SPAN",textNode("4.5")),element("SPAN",textNode("0")),element("SPAN",textNode("77")),element("SPAN",textNode("Бренд")));
const inlineParsed=parseNutritionSection(tokenText(inlineNutrition));
assert(inlineParsed&&inlineParsed.ккал===330&&inlineParsed.белки===4.5&&inlineParsed.жиры===0&&inlineParsed.углеводы===77,"Inline nutrition nodes were not separated: "+JSON.stringify(inlineParsed));
const fix=parseNutritionSection("Пищевая ценность в 100 г\nКкал\nБелки\nЖиры\nУглеводы\n151.8\n20\n5.1\n6.9\nБренд\nDaily Joy\nАртикул 1720085");
assert(fix&&fix.ккал===151.8&&fix.белки===20&&fix.жиры===5.1&&fix.углеводы===6.9,"Fix Price grouped layout failed");
const kuper=parseNutritionSection("Пищевая ценность на 100 г\nБелки\n3.0 г\nЖиры\n2.5 г\nУглеводы\n4.7 г\nКалорийность\n53.0 ккал\nСостав\nМолоко цельное");
assert(kuper&&kuper.белки===3&&kuper.жиры===2.5&&kuper.углеводы===4.7&&kuper.ккал===53,"Kuper paired layout failed: "+JSON.stringify(kuper));
const zeroFat=parseNutritionSection("Пищевая ценность на 100 г\nБелки\n1.8 г\nУглеводы\n5.4 г\nКалорийность\n26.0 ккал\nОбщая информация");
assert(zeroFat&&zeroFat.жиры===0&&zeroFat.кбжу_ноль_восстановлен==="жиры","Missing zero fat was not inferred safely: "+JSON.stringify(zeroFat));
const badEnergy=parseNutritionSection("Пищевая ценность на 100 г\nБелки\n4.4 г\nЖиры\n1.1 г\nУглеводы\n1.1 г\nКалорийность\n126.0 ккал\nОбщая информация");
assert(badEnergy&&/(кДж|не согласуется)/.test(validationIssue(badEnergy)),"Contradictory Kuper energy was not preserved for rejection: "+JSON.stringify(badEnergy));
assert(validationIssue({белки:90,жиры:1,углеводы:60,ккал:1}),"Impossible tea was accepted");
assert(/кДж/.test(validationIssue({белки:3,жиры:2.5,углеводы:4.7,ккал:223.4})),"kJ/kcal mismatch was not detected");
console.log("OK: nutrition parser layouts and validation");
`;

eval(core + tests);
