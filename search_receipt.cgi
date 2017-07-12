#!/usr/bin/perl

use strict;
use warnings;

use DBI;
use Fcntl qw/:flock SEEK_END/;

require "./conf.pl";

our($db,$db_user,$db_pwd,$log_d,$doc_root,$upload_dir);

my %session;
my %auth_params;

my $id;
my $logd_in = 0;
my $authd = 0;
my $accountant = 0;

my $con;
my ($key,$iv,$cipher) = (undef, undef,undef);

if ( exists $ENV{"HTTP_SESSION"} ) {

	my @session_data = split/&/,$ENV{"HTTP_SESSION"};
	my @tuple;

	for my $unprocd_tuple (@session_data) {
		#came to learn (as often happens, purely by accident)
		#doing a split/=/,x= will give a list with a size of 1
		#desirable here (where it's OK to ignore unset vars)
		#would be awful where even a blank var means something (e.g
		#logging in with a blank password)
		@tuple = split/\=/,$unprocd_tuple;

		if (@tuple == 2) {
			$tuple[0] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$tuple[1] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$session{$tuple[0]} = $tuple[1];		
		}
	}

	#logged in 
	if (exists $session{"id"}) {
		$logd_in++;
		$id = $session{"id"};
		#only bursar(user 2) or accountant can search for a receipt
		if ( $id eq "2" or ($id =~ /^\d+$/ and ($id % 17) == 0) ) {

			$accountant++;
			if (exists $session{"sess_key"} ) {
				$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

				use MIME::Base64 qw /decode_base64/;
				use Crypt::Rijndael;

				my $decoded = decode_base64($session{"sess_key"});
				my @decoded_bytes = unpack("C*", $decoded);

				my @sess_init_vec_bytes = splice(@decoded_bytes, 32);
				my @sess_key_bytes = @decoded_bytes;

				#read enc_keys_mem
				my $prep_stmt3 = $con->prepare("SELECT init_vec,aes_key FROM enc_keys_mem WHERE u_id=? LIMIT 1");

				if ( $prep_stmt3 ) {

					my $rc = $prep_stmt3->execute($id);

					if ( $rc ) {

						my ($mem_init_vec, $mem_aes_key) = (undef,undef);

						while (my @rslts = $prep_stmt3->fetchrow_array()) {
							$mem_init_vec = $rslts[0];
							$mem_aes_key = $rslts[1];
						}

						if ( defined $mem_init_vec ) {

							my @mem_init_vec_bytes = unpack("C*", $mem_init_vec);
							my @mem_aes_key_bytes = unpack("C*", $mem_aes_key);

							my ( @decrypted_init_vec, @decrypted_aes_key );

							for (my $i = 0; $i < @mem_init_vec_bytes; $i++) {
								$decrypted_init_vec[$i] = $mem_init_vec_bytes[$i] ^ $sess_init_vec_bytes[$i];
							}

							for (my $j = 0; $j < @mem_aes_key_bytes; $j++) {
								$decrypted_aes_key[$j] = $mem_aes_key_bytes[$j] ^ $sess_key_bytes[$j];
							}

							$key = pack("C*", @decrypted_aes_key);
							$iv = pack("C*", @decrypted_init_vec);

							$cipher = Crypt::Rijndael->new($key, Crypt::Rijndael::MODE_CBC());
							$cipher->set_iv($iv);

							$authd++;

						}
					}
					else {
						print STDERR "Couldn't execute SELECT FROM enc_keys_mem: ", $prep_stmt3->errstr, $/;
					}

				}
				else {
					print STDERR "Couldn't prepare SELECT FROM enc_keys_mem: ", $prep_stmt3->errstr, $/;
				}
			}
		}
	}
}

my $content = '';
my $feedback = '';
my $js = '';

my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Accounts Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/accounts/">Accounts</a> --&gt; <a href="/cgi-bin/search_receipt.cgi">Search Receipt</a>
	<hr> 
};

unless ($authd) {
	if ($logd_in) {
		my $err = qq!<p><span style="color: red">Sorry, you do not have the appropriate privileges to search for a receipt.</span> Only the bursar and accountants are authorized to take this action.!;

		#key issues?
		if ( $accountant ) {

			$err = qq!<p><span style="color: red">Sorry, could not obtain the encryption keys needed to manage accounts.</span> Try <a href="/cgi-bin/logout.cgi">logging out</a> and then log in again. If this problem persists, contact support.!;

		}

		$content .=
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Search Receipt</title>
</head>
<body>
$header

</body>
</html> 
*;
		print "Status: 200 OK\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";

		my $len = length($content);
		print "Content-Length: $len\r\n";

		my @new_sess_array = ();

		for my $sess_key (keys %session) {
			push @new_sess_array, $sess_key."=".$session{$sess_key};        
		}
		my $new_sess = join ('&',@new_sess_array);

		print "X-Update-Session: $new_sess\r\n";

		print "\r\n";
		print $content;
		exit 0;
	}
	else {
		print "Status: 302 Moved Temporarily\r\n";
		print "Location: /login.html?cont=/cgi-bin/search_receipt.cgi\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";
       		my $res = 
qq!
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Search Receipt</title>
</head>
<body>
$header
You should have been redirected to <a href="/login.html?cont=/cgi-bin/search_receipt.cgi">/login.html?cont=/cgi-bin/search_receipt.cgi</a>. If you were not, <a href="login.html?cont=/cgi-bin/search_receipt.cgi">Click Here</a> 
</body>
</html>!;

		my $content_len = length($res);	
		print "Content-Length: $content_len\r\n";
		print "\r\n";
		print $res;
		exit 0;
	}
}

my $post_mode = 0;
my $boundary = undef;
my $multi_part = 0;

if (exists $ENV{"REQUEST_METHOD"} and uc($ENV{"REQUEST_METHOD"}) eq "POST") {
	

	if (exists $ENV{"CONTENT_TYPE"}) {
		if ($ENV{"CONTENT_TYPE"} =~ m!multipart/form-data;\sboundary=(.+)!i) {
			$boundary = $1;
			$multi_part++;
		}
	}

	unless ($multi_part) {
		my $str = "";

		while (<STDIN>) {
        	       	$str .= $_;
	       	}

		my $space = " ";
		$str =~ s/\x2B/$space/ge;
		my @auth_req = split/&/,$str;

		for my $auth_req_line (@auth_req) {
			my $eqs = index($auth_req_line, "=");	
			if ($eqs > 0) {
				my ($k, $v) = (substr($auth_req_line, 0, $eqs), substr($auth_req_line, $eqs + 1));
				$k =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
				$v =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
				$auth_params{$k} = $v;
			}
		}
	}
	#processing data sent 
	$post_mode++;
}

PM: {
if ( $post_mode ) {

	unless ( exists $auth_params{"confirm_code"} and exists $session{"confirm_code"} and $auth_params{"confirm_code"} eq $session{"confirm_code"} ) {
		$feedback = qq!<span style="color: red">Invalid request.</span> Do not alter the hidden values in the HTML form.!;
		$post_mode = 0;
		last PM; 
	}

	unless (exists $auth_params{"receipt_nos"} and length($auth_params{"receipt_nos"}) > 0) {
		$feedback = qq!<span style="color: red">Invalid request.</span> You did not provide valid receipt number(s).!;
		$post_mode = 0;
		last PM;
	}
	
	my %receipts;
	my @possib_receipts = split/\s+/,$auth_params{"receipt_nos"};

	for my $possib_receipt (@possib_receipts) {

		if ($possib_receipt =~ /^\d+$/) {
			$receipts{$possib_receipt} = {};	
		}

		#ranges
		elsif ($possib_receipt =~ /^(\d+)\-(\d+)$/) {
			my $start = $1;
			my $stop = $2;
			
			#be kind to users, swap start 
			#and stop if reverse-ordered
			if ( $start > $stop ) {
				my $tmp = $start;
				$start = $stop;
				$stop = $tmp; 
			}

			for ( my $i = $start; $i <= $stop; $i++ ) {
				$receipts{$i} = {};	
			}
		}
	}

	unless ( scalar(keys %receipts) > 0) {
		$feedback = qq!<span style="color: red">Invalid request.</span> You did not provide any valid receipt number to search for.!;
		$post_mode = 0;
		last PM;
	}

	use Digest::HMAC_SHA1 qw/hmac_sha1_hex/;

	my $prep_stmt1 = $con->prepare("SELECT receipt_no,paid_in_by,class,amount,mode_payment,ref_id,votehead,time,hmac FROM receipts WHERE receipt_no=? LIMIT 1");
	my %rolls = ();
	my %mode_payment_lookup = ("1" => "Bank Deposit", "2" => "Cash", "3" => "Banker's Cheque", "4" => "Money Order");

	if ( $prep_stmt1 ) {

		for my $receipt (keys %receipts) {
	
			my $receipt_no = undef;
			my $rc = $prep_stmt1->execute($receipt);

			if ($rc) {

				while (my @rslts = $prep_stmt1->fetchrow_array() ) {

					$receipt_no = $rslts[0];	

					my $paid_in_by = remove_padding($cipher->decrypt($rslts[1]));
					my $class = remove_padding($cipher->decrypt($rslts[2]));
					my $amount = remove_padding($cipher->decrypt($rslts[3]));
					my $mode_payment = remove_padding($cipher->decrypt($rslts[4]));
					my $ref_id = remove_padding($cipher->decrypt($rslts[5]));
					my $votehead = remove_padding($cipher->decrypt($rslts[6]));
					my $time = remove_padding($cipher->decrypt($rslts[7]));

					if ( $amount =~ /^\d+(\.\d{1,2})?$/ ) {

						#check HMAC
						my $hmac = uc(hmac_sha1_hex($paid_in_by . $class . $amount . $mode_payment . $ref_id . $votehead . $time, $key));

						if ( $hmac eq $rslts[8] ) {

							$receipts{$receipt_no}->{"paid_in_by"} = $paid_in_by;
							
							my $mode_payment_descr = $mode_payment_lookup{$mode_payment};
							
							if ( $mode_payment eq "3" or $mode_payment eq "4" ) {
								$mode_payment_descr .= "($ref_id)";
							}

							$receipts{$receipt_no}->{"mode_payment"} = $mode_payment_descr;
							$receipts{$receipt_no}->{"amount"} = format_currency($amount);
							$receipts{$receipt_no}->{"payment_for"} = join(" ", map{ucfirst($_)} split(/\s+/,$votehead));

							my @date = localtime($time);
							my $f_time = sprintf "%02d/%02d/%d %02d:%02d:%02d", $date[3],$date[4]+1,$date[5]+1900,$date[2],$date[1],$date[0];	
							$receipts{$receipt_no}->{"time"} = $f_time;
							${$rolls{$class}}{$paid_in_by}++;
						}
					}
				}
			}

			else {
				print STDERR "Couldn't execute SELECT FROM receipts: ", $prep_stmt1->errstr, $/;
			}

			#no such receipt
			if (not defined $receipt_no) {
				delete $receipts{$receipt};
			}

		}
	}
	else {
		print STDERR "Couldn't prepare SELECT FROM receipts: ", $prep_stmt1->errstr, $/;
	}

	#read student metadata
	my %stud_lookup = ();

	if ( scalar(keys %rolls) > 0 ) {

		for my $roll (keys %rolls) {

			my @adms = keys %{$rolls{$roll}};
			my @where_clause_bts = ();

			foreach (@adms) {
				push @where_clause_bts, "adm=?";
			}

			my $where_clause = join(" OR ", @where_clause_bts);

			my $prep_stmt2 = $con->prepare("SELECT adm,s_name,o_names FROM `$roll`");

			if ($prep_stmt2) {

				my $rc = $prep_stmt2->execute();
				if ( $rc ) {
					while (my @rslts = $prep_stmt2->fetchrow_array()) {
						$stud_lookup{$rslts[0]} = $rslts[1] . " " . $rslts[2];
					}
				}
			}

		}

	}

	my $results = qq!<em>Your receipt search did not return any results. Perhaps there're no such receipt(s).!;

	if ( scalar(keys %receipts) > 0 ) {

		$results = 
qq!
<FORM method="POST" action="/cgi-bin/print_receipt.cgi">
<TABLE border="1" cellspacing="5%" cellpadding="5%">
<THEAD>
<TH><INPUT type="checkbox" onclick="check_all_receipts()" id="check_all">
<TH>Receipt No.
<TH>Paid in By
<TH>Mode Payment
<TH>Amount
<TH>Payment For
<TH>Time
</THEAD>
<TBODY>
!;
		for my $receipt (sort { $a <=> $b } keys %receipts) {

			my $paid_in_by = $receipts{$receipt}->{"paid_in_by"};
			if ( exists $stud_lookup{$paid_in_by} ) {
				$paid_in_by .= " (" . $stud_lookup{$paid_in_by} . ")";
			}

			$results .= qq!<TR><TD><INPUT type="checkbox" checked id="receipt_$receipt" name="receipt_$receipt" value="$receipt"><TD>$receipt<TD>$paid_in_by<TD>$receipts{$receipt}->{"mode_payment"}<TD>$receipts{$receipt}->{"amount"}<TD>$receipts{$receipt}->{"payment_for"}<TD>$receipts{$receipt}->{"time"}!;
		}
		$results .= 
qq!
</TBODY>
</TABLE>
<P><INPUT type="submit" name="print_view" value="Print/View">&nbsp;&nbsp;<INPUT type="button" onclick="rollback()" value="Rollback">
</FORM>
!;
	}

	my $receipts_js_str = join(",", sort { $a <=> $b } keys %receipts);

	$content =
qq*

<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Search Receipt</title>

<script type="text/javascript">

var receipts = [$receipts_js_str];
var content = '';

function check_all_receipts() {

	var state = document.getElementById("check_all").checked;	
	for (var i = 0; i < receipts.length; i++) {
		document.getElementById("receipt_" + receipts[i]).checked = state;
	}
}

function rollback() {

	content = document.getElementById("results").innerHTML;
	var new_content = '<FORM method="POST" action="/cgi-bin/rollback_receipt.cgi"><p>Clicking \\'confirm\\' will rollback the following receipts:<ul>';

	for (var i = 0; i < receipts.length; i++) {
		if ( document.getElementById("receipt_" + receipts[i]).checked ) {
			new_content += '<INPUT type="hidden" name="receipt_' + receipts[i] + '" value="' + receipts[i] + '">';
			new_content += '<li>' + receipts[i];
		}
	}
	
	new_content += '</ul><p><INPUT type="submit" value="Confirm" name="rollback">&nbsp;&nbsp;<INPUT type="button" value="Cancel" name="Cancel" onclick="cancel()">';
	new_content += '</FORM>';
	document.getElementById("results").innerHTML = new_content;
}

function cancel() {
	document.getElementById("results").innerHTML = content;
}

</script>
</head>
<body>
$header
$feedback
<div id="results">
$results
</div>
</body>
</html>
*;

}
}

if (not $post_mode) {

	my $conf_code = gen_token();
	$session{"confirm_code"} = $conf_code;

	$content = 
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Search Receipt</title>

<script type="text/javascript">

var receipt_no_re = /^([0-9]\*(\\-[0-9]\*)?\\s\*)\*\$/;

function check_receipt_nos() {

	var receipt_numbers = document.getElementById("receipt_nos").value;
	if (receipt_numbers.match(receipt_no_re)) {
		document.getElementById("receipt_nos_err").innerHTML = "";
	}
	else {
		document.getElementById("receipt_nos_err").innerHTML = "\*";
	}
}

function check_balance_expr() {
	var expr = document.getElementById("balance_expr").value;
	if (expr.match(balance_expr_re)) {
		document.getElementById("balance_expr_err").innerHTML = "";
	}
	else {
		document.getElementById("balance_expr_err").innerHTML = "\*";
	}
}

</script>
</head>
<body>
$header
$feedback

<FORM method="POST" action="/cgi-bin/search_receipt.cgi">
<input type="hidden" name="confirm_code" value="$conf_code">

<span id="receipt_nos_err" style="color: red"></span><label for="receipt_no">Receipt no(s)</label>&nbsp;<input type="text" size="50" name="receipt_nos" id="receipt_nos" onkeyup="check_receipt_nos()">&nbsp;&nbsp;<em>You can include ranges like 334-345</em>
<p><INPUT type="submit" name="search" value="Search">
</FORM>

</body>
</html>
*;

}

print "Status: 200 OK\r\n";
print "Content-Type: text/html; charset=UTF-8\r\n";

my $len = length($content);
print "Content-Length: $len\r\n";

my @new_sess_array = ();

for my $sess_key (keys %session) {
	push @new_sess_array, $sess_key."=".$session{$sess_key};        
}
my $new_sess = join ('&',@new_sess_array);

print "X-Update-Session: $new_sess\r\n";

print "\r\n";
print $content;
$con->disconnect() if (defined $con and $con);

sub gen_token {
	my @key_space = ("A","B","C","D","E","F","0","1","2","3","4","5","6","7","8","9");
	my $len = 5 + int(rand 15);
	if (@_ and ($_[0] eq "1")) {
		@key_space = ("A","B","C","D","E","F","G","H","J","K","L","M","N","P","T","W","X","Z","7","0","1","2","3","4","5","6","7","8","9");
		$len = 10 + int (rand 5);
	}
	my $token = "";
	for (my $i = 0; $i < $len; $i++) {
		$token .= $key_space[int(rand @key_space)];
	}
	return $token;
}

sub htmlspecialchars {
	my $cp = $_[0];
	$cp =~ s/&/&#38;/g;
        $cp =~ s/</&#60;/g;
        $cp =~ s/>/&#62;/g;
        $cp =~ s/'/&#39;/g;
        $cp =~ s/"/&#34;/g;
        return $cp;
}

sub remove_padding {

	return undef unless (@_);

	my $packed = $_[0];
	my @bytes = unpack("C*", $packed);
	
	my $final_index = $#bytes;
	my $pad_size = $bytes[$final_index];

	my $msg_valid = 1;
	#verify msg
	
	for ( my $i = 1; $i < $pad_size; $i++ ) {
		unless ( $bytes[$final_index - $i] == $pad_size ) {
			$msg_valid = 0;
			last;
		}
	}

	if ($msg_valid) {
		my $msg_size = ($final_index + 1) - $pad_size;
		my $msg = unpack("A${msg_size}", $packed);

		return $msg;
	}
	return undef;
}

sub add_padding {

	return undef unless (@_);

	my $tst_str = $_[0];
	my $tst_str_len = length($tst_str);

	my $rem = 16 - ($tst_str_len % 16);
	if ($rem == 0 ) {
		$rem = 16;
	}

	my @extras = ();
	for (my $i = 0; $i < $rem; $i++) {
		push @extras, $rem;
	}

	my $padded = pack("A${tst_str_len}C${rem}", $tst_str, @extras);
	return $padded;
}

sub format_currency {

	return "" unless (@_);

	my $formatted_num = $_[0];

	if ( $_[0] =~ /^(\-?)(\d+)(\.(?:\d))?$/ ) {

		my $sign = $1;
		my $shs = $2;
		my $cents = $3;

		$sign = "" if (not defined $sign);
		$cents = "" if (not defined $cents);

		my $num_blocks = int(length($shs) / 3);

		if ($num_blocks > 0) {

			my @nums = ();

			my $surplus = length($shs) % 3;
			if ($surplus > 0) {
				push @nums, substr($shs, 0, $surplus);
			}

			for (my $i = 0; $i < $num_blocks; $i++) {
				push @nums, substr($shs, $surplus + ($i * 3),3);
			}

			$formatted_num = join(",", @nums); 
		}

		$formatted_num = $sign . $formatted_num;
		$formatted_num .= $cents;
	}
	return $formatted_num;
}
