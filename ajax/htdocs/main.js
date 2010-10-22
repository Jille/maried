function _tr(data) {
	n_tr = document.createElement('tr');
	for(var i = 0; i < data.length; i++) {
		n_td = document.createElement('td');
		n_td.appendChild(document.createTextNode(data[i]));
		n_tr.appendChild(n_td);
	}
	return n_tr;
}

function Main() {
	this.focus_queryField = function() {
		$("#queryField").focus();
	}
	this.on_scroll = function() {
		var me = this;
		if(this.scroll_semaphore != 0)
			return;
		if(!this.showing_results)
			return;
		var diff = $(document).height() -
			   $(document).scrollTop() -
			   $(window).height();
		if (diff <= 0) {
			this.fill_resultsTable();
			setTimeout(function() {
				me.on_scroll();	
			},0)
		}
	}
	this.up_scroll_semaphore = function() {
		this.scroll_semaphore += 1;
		if(this.scroll_semaphore == 0)
			this.on_scroll();
	};
	this.down_scroll_semaphore = function() {
		this.scroll_semaphore -= 1;
	};
	this.on_loginForm_submit = function(e) {
		$.unblockUI();
		createCookie('user', $('#loginFormUser').val());
		createCookie('pass', $('#loginFormPass').val());
		this.raise('new_credentials');
	};
	this.on_loginForm_keyDown = function(e) {
		if(e.which == 27) {
			$.unblockUI();
		} else if(e.which == 13) {
			this.on_loginForm_submit(e);
		}
	};
	this.raise = function(ev) {
		for (var i = 0; i < this.handlers[ev].length; i++) {
			this.handlers[ev][i]();
		}
		this.handlers[ev] = [];
	};
	this.catch_once = function(ev, h) {
		this.handlers[ev][this.handlers[ev].length] = function() {
			h();
		};
	};
	this.run = function() {
		var me = this;
		$.blockUI.defaults.applyPlatformOpacityRules = false;
		this.handlers = {new_credentials: []};
		this.loginForm = $('#loginForm');
		this.loginForm.hide();
		$("#loginFormUser").keydown(function(e) {
				me.on_loginForm_keyDown(e);
			});
		$("#loginFormPass").keydown(function(e){
				me.on_loginForm_keyDown(e);
			});
		$("#loginFormSubmit").click(function(e){
				me.on_loginForm_submit(e);
			});
		this.queryCheck = /^[a-z0-9 ]*$/;
		this.queryReplace = /[^a-z0-9 ]/g;
		this.focus_queryField();
		//$("#queryField").blur(function(){
		//	setTimeout(function() { me.focus_queryField(); }, 0);
		//});
		$(document).scroll(function() { me.on_scroll(); });
		$(window).focus(this.focus_queryField);
		$("#resultsBar").hide();
		$("#requestsBar").focus(this.focus_queryField);
		$("#queryField").keypress(function(e){
			return me.on_queryField_keyPress(e);
		});
		$("#queryField").keydown(function(e){
			setTimeout(function() { me.check_queryField(); }, 0);
		});
		this.showing_results = false;
		this.fetch_media();
		this.fetch_requests();
		this.fetch_playing();
		this.fetching_media = false;
		this.fetching_requests = false;
		this.fetching_playing = false;
		this.got_media = false;
		this.got_requests = false;
		this.got_playing = false;
		this.update_requests = false;
		this.update_results = false;
		this.updating_times = false;
		this.current_query = '';
		this.results_offset = null;
		this.scroll_semaphore = 0;
	};

	this.do_updates = function() {
		var me = this;
		if(this.update_requests) {
			this.update_requests = false;
			$("#requestsTable").empty();
			this.fill_requestsTable();
		}
		if(this.update_results) {
			$("#resultsTable").empty();
			this.results_offset = 0;
			this.fill_resultsTable();
			setTimeout(function() {
				me.on_scroll();
			}, 0);
			this.update_results = false;
		}
		if(this.got_playing && !this.updating_times) {
			this.updating_times = true;
			setInterval(function() {
				me.update_times();
			}, 1000);
		}
	};

	this.update_times = function() {
		var me = this;
		var diff = (this.playing_endTime
			    - new Date().getTime() / 1000.0
			    - this.playing_serverTime
			    + this.playing_requestTime);
		$('#requestsTable tr').each(function(i, tr){
			var offset = $(tr).data('offset');
			$('.time', tr).text(offset == null ? '' 
					: nice_time(offset + diff));
		});
		if(diff <= 0) {
			this.fetch_requests();
			this.fetch_playing();
		}
	};

	this.do_query = function() {
		var cq = this.current_query;
		for(var s = cq.length;
		    !this.qc[cq.slice(0, s)];
		    s--);
		for(var i = s; i < cq.length; i++) {
			var from = cq.slice(0, i);
			var to = cq.slice(0, i + 1);
			var k = 0;
			this.qc[to] = [];
			for(var j = 0; j < this.qc[from].length; j++) {
				if(this.qc[from][j][1].indexOf(to) != -1) {
					this.qc[to][k] = this.qc[from][j];
					k += 1;
				}
			}
		}
	};

	this.fill_resultsTable = function() {
		var me = this;
		var t = $("#resultsTable");
		var cq = this.current_query;
		if(!this.got_media)
			return;
		this.do_query();
		var got = 0;
		for(; this.results_offset < this.qc[cq].length; this.results_offset++) {
			got += 1;
			var i = this.results_offset;
			var m = this.media['_'+this.qc[cq][i][0]];
			var tr = _tr([m[0], m[1]]);
			$(tr).data('key', this.qc[cq][i][0]);
			$('td:eq(0)',tr).addClass('artist');
			$('td:eq(1)',tr).addClass('title');
			$(tr).click(function() {
					$("#queryField").val("");
					me.check_queryField();
					$("#queryField").focus();
					me.request_media($(this).data('key'));
				});
			t.append(tr);
			if(got == 10) break;
		}
		this.results_offset++;
	};

	this.fill_requestsTable = function() {
		var t = $("#requestsTable");
		var start = (this.got_playing ? -1 : 0);
		var end = (this.got_requests ? this.requests.length : 0);
		var ctime = null;
		for(var i = start; i < end; i++) {
			var m = (i == -1 ? this.playing_media
				: this.requests[i].media);
			var b = (i == -1 ? this.playing_requestedBy
				: this.requests[i].by);
			if(!b) b = 'marietje';
			var txt_a = m;
			var txt_t = '';
			if(this.got_media) {
				txt_a = this.media['_'+m][0];
				txt_t = this.media['_'+m][1];
			}
			tr = _tr([b, txt_a, txt_t, (ctime == null ? '' : ctime)]);
			$(tr).data('offset', ctime);
			ctime = (i == -1 ? 0 : 
				(this.got_media ?
				 ctime + this.media['_'+m][2] : 0));
			$('td:eq(0)',tr).addClass('by');
			$('td:eq(1)',tr).addClass('artist');
			$('td:eq(2)',tr).addClass('title');
			$('td:eq(3)',tr).addClass('time');
			t.append(tr);
		}
	};

	this.show_loginForm = function() {
		var me =this;
		setTimeout(function() {
			$.blockUI({message: me.loginForm });
		}, 1000);
	};

	this.request_media = function(key) {
		var me = this;
		if(readCookie('user') == null ||
		   readCookie('pass') == null) {
			this.catch_once('new_credentials', function() {
				me.request_media(key);
			});
			this.show_loginForm();
			return;
		}
		$.get("/request/"+readCookie('user') + "/" +
				  readCookie('pass') + "/" +
				  key.toString(), function (doc) {
				me.on_requested_media(doc);
			});
	};

	this.on_requested_media = function(doc) {
		var code = $(doc.firstChild).attr('code');
		if(code == 'wrong-login') {
			this.show_loginForm();
			return;
		} else if (code == 'ok') {
			this.fetch_requests();
			$.growlUI('Success', 'Your request was succesfull');
		} else if (code == 'denied') {
			$.growlUI('Denied', $(doc.firstChild).attr('message'));
		}
	};

	this.check_queryField = function(e) {
		var me = this;
		var q = $("#queryField").val();
		if(!this.queryCheck.test(q)) {
			q = q.toLowerCase().replace(this.queryReplace, '');
			$("#queryField").val(q);
		}
		if(q == this.current_query)
			return;
		this.current_query = q;
		_cb = function() { me.up_scroll_semaphore(); };
		if(q == '' && this.showing_results){
			this.down_scroll_semaphore();
			this.down_scroll_semaphore();
			$('#resultsBar').hide('fast', _cb);
			$('#requestsBar').show('fast', _cb);
			this.showing_results = false;
		} else if (q != '' && !this.showing_results) {
			this.down_scroll_semaphore();
			this.down_scroll_semaphore();
			$('#resultsBar').show('fast', _cb);
			$('#requestsBar').hide('fast', _cb);
			this.showing_results = true;
		}
		if(q != '') {
			this.update_results = true;
			this.do_updates();
		}

	};

	this.on_queryField_keyPress = function(e) {
		var me = this;
		if(e.which == 21) // C-u
			$("#queryField").val('');
		setTimeout(function() { me.check_queryField(); }, 0);
	};

	this.fetch_media = function() {
		var me = this;
		if(this.fetching_media) return;
		this.fetching_media = true;
		$.getJSON('/media', function(req) {
			me.on_got_media(req);
		});
	};
	this.fetch_requests = function() {
		var me = this;
		if(this.fetching_requests) return;
		this.fetching_requests = true;
		$.get('/requests', function(req) {
			me.on_got_requests(req);
		});
	};
	this.fetch_playing = function() {
		var me = this;
		if(this.fetching_playing) return;
		this.fetching_playing = true;
		$.get('/playing', function(req) {
			me.on_got_playing(req);
		});
	};

	this.on_got_media = function(req) {
		var me = this;
		this.got_media = true;
		this.fetching_media = false;
		this.media = req;
		this.qc = {'': []};
		var i = 0;
		for(var _k in req) {
			var cr = this.queryReplace;
			var k = _k.slice(1);
			me.qc[''][i++] = [
				k,
				req[_k][0].toLowerCase().replace(cr, '') + '|' +
				req[_k][1].toLowerCase().replace(cr, '')];
		};
		this.update_requests = true;
		this.update_results = true;
		this.do_updates();
	};
	this.on_got_requests = function(req) {
		var me = this;
		this.got_requests = true;
		this.fetching_requests = false;
		this.requests = [];
		$("request", req).each(function(i, r) {
			m = $(r);
			me.requests[i] = {
				media: m.attr('media'),
				by: m.attr('by')
			};
		});
		this.update_requests = true;
		this.do_updates();
	};
	this.on_got_playing = function(req) {
		this.got_playing = true;
		this.fetching_playing = false;
		var m = $(req.firstChild);
		this.playing_media = m.attr('media');
		this.playing_requestedBy = m.attr('requestedBy');
		this.playing_endTime = parseFloat(m.attr('endTime'));
		this.playing_serverTime = parseFloat(m.attr('serverTime'));
		this.playing_requestTime = new Date().getTime() / 1000.0;
		this.update_requests = true;
		this.do_updates();
	};
}

main = new Main();
$(document).ready(function(){main.run();});

