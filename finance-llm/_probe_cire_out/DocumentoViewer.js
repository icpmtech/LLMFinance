var DocumentViewerJS = {

    Ver: function (btnVerMaisControl, btnFecharId, viewerId, ifrDocId, queryStringId, url) {

        var btnVerMais = $(btnVerMaisControl);
        var container = btnVerMais.parent("div");
        var btnFechar = container.find("#" + btnFecharId);
        var viewer = container.find("#" + viewerId);
        var iframe = container.find("#" + ifrDocId);
        var queryString = container.find("#" + queryStringId);

        url = url + "q=" + queryString.val();

        btnVerMais.hide();
        btnFechar.show();
        viewer.show();
        queryString.show();

        $(iframe).attr("src", url).slideDown("normal");
    },

    Fechar: function (btnFecharControl, btnVerMaisId, viewerId, ifrDocId) {

        var btnFechar = $(btnFecharControl);
        var container = btnFechar.parent("div");
        var btnVerMais = container.find("#" + btnVerMaisId);
        var viewer = container.find("#" + viewerId);
        var iframe = container.find("#" + ifrDocId);

        btnVerMais.show();
        btnFechar.hide();

        $(iframe).slideUp("normal");
        viewer.hide();
    }
};

var Viewer = {

    Abrir: function (btnVerMaisControl, id, method, btnFecharId, updatePanelId) {

        var btnAbrir = $(btnVerMaisControl);
        var container = btnAbrir.parent("div");;
        var updatePanel = container.find("#" + updatePanelId);
        var btnFechar = container.find("#" + btnFecharId);

        this.ID = updatePanel;

        if ($.trim(updatePanel.html()) == "") {

            updatePanel.show();
            updatePanel.html("<p> A carregar... por favor aguarde.</p>").slideDown("normal");

            var data = "{htmlId:" + id + "}";
            var context_this = this;

            $.ajax({
                type: "POST",
                url: method,
                data: data,
                contentType: "application/json; charset=utf-8",
                dataType: "json",
                success: function (html) {

                    var id = context_this.ID;
                    id.show();
                    id.html(html.d).slideDown("normal");
                }
            });
        }
        else {


            updatePanel.slideDown("normal");
            updatePanel.show();
        }

        btnAbrir.hide();
        btnFechar.show();

    },

    Error: function (msg) {
        alert(msg);
    },

    Fechar: function (btnFecharControl, btnAbrirId, updatePanelId) {

        var btnFechar = $(btnFecharControl);
        var container = btnFechar.parent().parent();
        var btnAbrir = container.find("#" + btnAbrirId);
        var updatePanel = container.find("#" + updatePanelId);

        updatePanel.slideUp("normal");
        updatePanel.hide();
        btnAbrir.show();
        btnFechar.hide();
    }
};

/*
var Html = {

    // Mostra e esconde os detalhes da publicidade insolvencia
    toggleDetails: function (id) {

        $("#divVerMais_" + id).each( function() {
    
            var details = $("#Details_" + id);
    
            // Fecha ou abre os detalhes em função da classe atribuida ao link
            if ($(this).hasClass("vermais"))
            { 
                // Só vai fazer a chamada ajax caso os detalhes estejam vazios
                if (details.html() == "")
                {
                   // chamar PageMethod
                    PageMethods.GetDetailHtml(id, function(result){OnSuccedeed(result, id);}, OnFailed);
                }
                else // Senão apenas tem de mudar o icone do link e o texto
                {
                     $(this).removeClass("vermais").addClass("vermaisup").children("a").text("fechar");
                    details.slideDown("normal"); // Mostra os detalhes
               }
            }
            else 
            {   // Esconde os detalhes e muda a classe do link
                    details.slideUp("normal");
                    $(this).removeClass("vermaisup").addClass("vermais").children("a").text("ver mais");
            }
         });
    },         

    // Caso consiga obter os dados,concatena a div com o html do detalhe e esconde a animação do ajax.
    OnSuccedeed: function (result, id)
    {
      result = "<div id=divdetalhecdital>" + result + "</div>"
      $("#Details_" + id).slideDown("normal").html(result);
      $("#divVerMais_" + id).removeClass("vermais").addClass("vermaisup").children("a").text("fechar");
      
    },

    // Lança msg de erro em caso de nao conseguir obter os dados e esconde a animação do ajax
    OnFailed: function (error)
    {
        alert(error.get_message());
    }
};*/