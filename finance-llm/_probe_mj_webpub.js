function isEmpty(elem, sName) {
    if (elem.value == '') {
        alert('Por favor preencha o campo ' + sName);
        elem.focus();
        return true;
    }
    return false;
}
function stripHTML() {
    var re = /<\S[^><]*>/g
    for (i = 0; i < arguments.length; i++)
        arguments[i].value = arguments[i].value.replace(re, "")
}
function validaDados(intPage) {
    switch (intPage) {
        case 1:
            if (isEmpty(document.forms[0].dfNome, 'Nome')) { return false; }
            if (isEmpty(document.forms[0].dfMorada, 'Resid�ncia/Sede')) { return false; }
            if (isEmpty(document.forms[0].dfLocalidade, 'Localidade')) { return false; }
            if (isEmpty(document.forms[0].dfContacto, 'Contacto Telef�nico')) { return false; }
            if (isEmpty(document.forms[0].dfEmail, 'Endere�o electr�nico')) { return false; }
            if (document.forms[0].dfEmail.value != '') {
                if (!verifyMail(document.forms[0].dfEmail.value)) {
                    alert('O endere�o de correio electr�nico n�o � v�lido');
                    return false;
                }
            }
            if (!verifyNIF(document.forms[0].dfNIF, 'NIF/NIPC')) { return false; }
            if (isEmpty(document.forms[0].dfEntidade, 'Entidade')) { return false; }
            if (isEmpty(document.forms[0].dfDistrito, 'Sede - Distrito')) { return false; }
            if (isEmpty(document.forms[0].dfConcelho, 'Sede - Concelho')) { return false; }
            if (isEmpty(document.forms[0].dfActo, 'Acto')) { return false; }
            //Acto
            if (document.forms[0].dfActo.value == 5 || document.forms[0].dfActo.value == 12) {
                if (isEmpty(document.forms[0].dfOutroActo, 'Outro Acto')) { return false; }
                document.forms[0].dfActoDesc.value = document.forms[0].dfOutroActo.value;
            } else {
                document.forms[0].dfActoDesc.value = document.forms[0].dfActo.options[document.forms[0].dfActo.selectedIndex].text;
            }
            break;
        case 2:
            if (isEmpty(document.forms[0].dfPubTexto, 'Texto a Publicar')) { return false; }
            if (!checkLength(document.forms[0].dfPubTexto, 500000, 'Texto a Publicar')) { return false; }
            break;
        case 3:
            if (isEmpty(document.forms[0].dfFile, 'Ficheiro a Publicar')) { return false; }
            return checkFileUploadRules(document.forms[0].dfFile.value);
            break;
        default:
            //No validation required
    }
    ProcessPublicacao();
    return true;
}

function checkFileUploadRules(sFileName) {
    var intMaxFileSize = 5120;
    var strAllowedExtensions = "pdf";
    var agt = navigator.userAgent.toLowerCase();

    //verifica se � navigator (mozilla), para compatibilidade com firefox
    var is_nav = ((agt.indexOf('mozilla') != -1) && (agt.indexOf('spoofer') == -1)
                && (agt.indexOf('compatible') == -1) && (agt.indexOf('opera') == -1)
                && (agt.indexOf('webtv') == -1) && (agt.indexOf('hotjava') == -1));

    var sArray = sFileName.split(".");

    if (sArray.length < 2) {
        alert("O nome do ficheiro � incorrecto.");
        return false;
    }

    var ext = sArray[sArray.length - 1];

    if (ext.toUpperCase() != strAllowedExtensions.toUpperCase()) {
        alert("O ficheiro � do tipo incorrecto.\r\nDever� ser do tipo '" + strAllowedExtensions + "'.");
        return false;
    }
    //IE
    //if(!is_nav){
    //var oFile = new ActiveXObject("Scripting.FileSystemObject");
    //var file = oFile.getFile(sFileName);
    //var size = file.size;
    //}
    //Mozilla
    //else{
    //return false;
    //}

    return true;
}

function verifyNIF(oField, sFieldName) {
    var i = oField.value.length;
    if (i < 9) {
        alert('O campo \'' + sFieldName + '\' cont�m um n�mero fiscal inv�lido.');
        oField.focus();
        return false;
    }
    if (isNaN(parseInt(oField.value))) {
        alert('O campo \'' + sFieldName + '\' cont�m um n�mero fiscal inv�lido.');
        oField.focus();
        return false;
    }
    var iDiv = 0;
    var nif = new String(oField.value)
    iDiv = parseInt(nif.substr(0, 1)) * 9 + parseInt(nif.substr(1, 1)) * 8 + parseInt(nif.substr(2, 1)) * 7;
    iDiv = iDiv + parseInt(nif.substr(3, 1)) * 6 + parseInt(nif.substr(4, 1)) * 5 + parseInt(nif.substr(5, 1)) * 4;
    iDiv = iDiv + parseInt(nif.substr(6, 1)) * 3 + parseInt(nif.substr(7, 1)) * 2;
    var iResto = iDiv % 11;
    var iCheckDig = 11 - iResto;
    if (iCheckDig > 9) iCheckDig = 0;
    var iCheckDigNif = parseInt(nif.substr(8, 1));
    if (iCheckDig != iCheckDigNif) {
        alert('O campo ' + sFieldName + ' n�o � valido.');
        oField.focus();
        return false;
    }
    return true;
}
function getObj(name) {
    if (document.getElementById) { return document.getElementById(name); }
    else if (document.all) { return document.all[name]; }
    else if (document.layers) { return document.layers[name]; }
}
function checkLength(oField, sSize, sName) {
    if (oField.value.length > sSize) {
        alert("O campo " + sName + " cont�m " + oField.value.length + " caracteres. O tamanho m�ximo permitido � de " + sSize + " caracteres.");
        oField.focus();
        return false;
    }
    return true;
}

function formatDate(element) {
    if (doValidAux(element)) {
        if (element.value.length > 0) {
            Value2 = RegExp.$1 + RegExp.$2 + RegExp.$3;
            element.value = RegExp.$1 + "-" + RegExp.$2 + "-" + RegExp.$3;
            element.style.color = "black";
        } else {
            Value2 = element.value;
        }
    } else {
        element.style.color = "#ff0000";
        Value2 = element.value;
    }

}

function doValidAux(element) {
    var re = new RegExp("^(\\d{4})-?(\\d{2})-?(\\d{2})$", "ig");

    if (!re.exec(element.value)) { return false; }

    try {
        var dat = new Date(parseInt(RegExp.$1, 10), parseInt(RegExp.$2, 10) - 1, parseInt(RegExp.$3, 10));
        return (dat.getFullYear() == RegExp.$1) &&
		       (trailingZeros(String(dat.getMonth() + 1), 2) == RegExp.$2) &&
		       (trailingZeros(String(dat.getDate()), 2) == RegExp.$3);
    }
    catch (e) { return false; }
}

function trailingZeros(sStr, iLen) {
    while (sStr.length < iLen) sStr = "0" + sStr;
    return sStr;
}
function popitup(url, name) {
    window.open(url, name, config = 'toolbar=no, menubar=no, scrollbars=yes, resizable=1, directories=no, status=no');
    return false;
}

function toggleVisibility(strId) {
    el = getObj(strId);
    var display = el.style.display ? '' : 'none';
    el.style.display = display;
}

function daysBetween(date1, date2) {
    var DSTAdjust = 0;
    // constants used for our calculations below
    oneMinute = 1000 * 60;
    var oneDay = oneMinute * 60 * 24;
    // equalize times in case date objects have them
    date1.setHours(0);
    date1.setMinutes(0);
    date1.setSeconds(0);
    date2.setHours(0);
    date2.setMinutes(0);
    date2.setSeconds(0);
    // take care of spans across Daylight Saving Time changes
    if (date2 > date1) {
        DSTAdjust =
            (date2.getTimezoneOffset() - date1.getTimezoneOffset()) * oneMinute;
    } else {
        DSTAdjust =
            (date1.getTimezoneOffset() - date2.getTimezoneOffset()) * oneMinute;
    }
    var diff = (date2.getTime() - date1.getTime()) - DSTAdjust;
    return Math.ceil(diff / oneDay);
}

function validarDadosPesquisa() {
    var data1, data2, ndias;

    if (document.forms[0].iNIPC.value == '' && document.forms[0].sFirma.value == '' && document.forms[0].dfConcelho.value == '' && document.forms[0].dInicial.value == '') {
        alert('Tem de especificar pelo menos um dos crit�rios de pesquisa.');
        return false;
    }
    else if (document.forms[0].iNIPC.value == '' && document.forms[0].sFirma.value == '' && document.forms[0].dInicial.value == '') {
        alert('Tem de especificar pelo menos a data inicial.');
        return false;
    }
    if (document.forms[0].iNIPC.value != '' && !verifyNIF(document.forms[0].iNIPC, 'NIF/NIPC')) {
        return false;
    }
    if (document.forms[0].dInicial.value != '') {
        if (doValidAux(document.forms[0].dInicial)) {
            data1 = new Date(RegExp.$1, RegExp.$2 - 1, RegExp.$3);
        } else {
            alert('O campo data inicial possui uma data inv�lida.');
            return false;
        }
    }
    if (document.forms[0].dFinal.value != '') {
        if (doValidAux(document.forms[0].dFinal)) {
            data2 = new Date(RegExp.$1, RegExp.$2 - 1, RegExp.$3);
        } else {
            alert('O campo data final possui uma data inv�lida.');
            return false;
        }
    }
    if (data1 != null && data2 != null) {
        ndias = daysBetween(data1, data2)
        if (ndias < 0) {
            alert('A data final tem que ser superior � data inicial.');
            return false;
        } else if (ndias > 10) {
            alert('N�o pode indicar intervalos de datas superiores a 10 dias.');
            return false;
        }
    }
    else if (data1 != null) {
        data2 = new Date();
        ndias = daysBetween(data1, data2)
        if (ndias > 10) {
            alert('N�o pode indicar intervalos de datas superiores a 10 dias.');
            return false;
        }
    }
}

function validarDadosReceita() {
    var data1, data2, ndias;

    if (document.forms[0].dInicial.value != '') {
        if (doValidAux(document.forms[0].dInicial)) {
            data1 = new Date(RegExp.$1, RegExp.$2 - 1, RegExp.$3);
        } else {
            alert('O campo data inicial possui uma data inv�lida.');
            return false;
        }
    }
    if (document.forms[0].dFinal.value != '') {
        if (doValidAux(document.forms[0].dFinal)) {
            data2 = new Date(RegExp.$1, RegExp.$2 - 1, RegExp.$3);
        } else {
            alert('O campo data final possui uma data inv�lida.');
            return false;
        }
    }
    if (data1 != null && data2 != null) {
        ndias = daysBetween(data1, data2)
        if (ndias < 0) {
            alert('A data final tem que ser superior � data inicial.');
            return false;
        } else if (ndias > 30) {
            alert('N�o pode indicar intervalos de datas superiores a 30 dias.');
            return false;
        }
    }
}

function validarDadosPesquisaIES() {

    if (document.forms[0].iNIPC.value == '' || document.forms[0].iAno.value == '') {
        alert('Os campos NIF/NIPC e Ano s�o de preenchimento obrigat�rio.');
        return false;
    }
    if (document.forms[0].iNIPC.value != '' && !verifyNIF(document.forms[0].iNIPC, 'NIF/NIPC')) {
        return false;
    }
    if (isNaN(parseInt(document.forms[0].iAno.value))) {
        alert('O campo Ano cont�m um n�mero inv�lido.');
        return false;
    }

}
function verifyMail(str) {
    var filter = /^.+@.+\..{2,3}$/
    return (filter.test(str))
}

function validarPesquisaPendentes() {
    var data1, data2, ndias;

    if (document.forms[0].dInicial.value != '') {
        if (doValidAux(document.forms[0].dInicial)) {
            data1 = new Date(RegExp.$1, RegExp.$2 - 1, RegExp.$3);
        } else {
            alert('O campo data inicial possui uma data inv�lida.');
            return false;
        }
    }
    if (document.forms[0].dFinal.value != '') {
        if (doValidAux(document.forms[0].dFinal)) {
            data2 = new Date(RegExp.$1, RegExp.$2 - 1, RegExp.$3);
        } else {
            alert('O campo data final possui uma data inv�lida.');
            return false;
        }
    }
    if (data1 != null && data2 != null) {
        ndias = daysBetween(data1, data2)
        if (ndias < 0) {
            alert('A data final tem que ser superior � data inicial.');
            return false;
        }
    }
}

function ProcessPublicacao() {
    //Set the limit for field size.
    var FormLimit = 102399;

    //Get the value of the large input object.
    var TempVar = new String;
    TempVar = document.WebPub.dfPubTexto.value;

    //If the length of the object is greater than the limit, break it
    //into multiple objects.
    if (TempVar.length > FormLimit) {
        document.WebPub.dfPubTexto.value = TempVar.substr(0, FormLimit);
        TempVar = TempVar.substr(FormLimit);

        while (TempVar.length > 0) {
            var objTEXTAREA = document.createElement("TEXTAREA");
            objTEXTAREA.name = "dfPubTexto";
            objTEXTAREA.value = TempVar.substr(0, FormLimit);
            objTEXTAREA.style.display = 'none';
            document.WebPub.appendChild(objTEXTAREA);

            TempVar = TempVar.substr(FormLimit);
        }
    }
}

function Scroll() {
    window.scrollTo(0, 600)
}
