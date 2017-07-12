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

my $query_mode = 0;
my $page = 1;
my $per_page = 10;

my $search_string = "";
my $encd_search_str = "";

my $sort_order = 0;
my $sort_by = 0;

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
		#only bursar(user 2) and accountant(mod 17) can view creditors
		if ($id eq "2" or ($id =~ /^\d+$/ and ($id % 17) == 0) ) {

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

	if (exists $session{"per_page"} and $session{"per_page"} =~ /^(\d+)$/) {
		$per_page = $1;
	}

	if (exists $session{"creditors_sort_order"} and $session{"creditors_sort_order"} =~ /^([01])$/) {
		$sort_order = $1;
	}

	if (exists $session{"creditors_sort_by"} and $session{"creditors_sort_by"} =~ /^([0123])$/) {
		$sort_by = $1;
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
	<p><a href="/">Home</a> --&gt; <a href="/accounts/">Accounts</a> --&gt; <a href="/cgi-bin/creditors.cgi">View Creditors</a>
	<hr> 
};

unless ($authd) {
	if ($logd_in) {
		my $err = qq!<p><span style="color: red">Sorry, you do not have the appropriate privileges to view creditors.</span> Only the bursar and accountant(s) are authorized to take this action.!;

		#key issues?
		if ( $accountant ) {

			$err = qq!<p><span style="color: red">Sorry, could not obtain the encryption keys needed to manage accounts.</span> Try <a href="/cgi-bin/logout.cgi">logging out</a> and then log in again. If this problem persists, contact support.!;

		}

		$content .=
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::View Creditors</title>
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
		print "Location: /login.html?cont=/cgi-bin/creditors.cgi\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";
       		my $res = 
qq!
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::View Creditors</title>
</head>
<body>
$header
You should have been redirected to <a href="/login.html?cont=/cgi-bin/creditors.cgi">/login.html?cont=/cgi-bin/creditors.cgi</a>. If you were not, <a href="login.html?cont=/cgi-bin/creditors.cgi">Click Here</a> 
</body>
</html>!;

		my $content_len = length($res);	
		print "Content-Length: $content_len\r\n";
		print "\r\n";
		print $res;
		exit 0;
	}
}

if ( exists $ENV{"QUERY_STRING"} ) {

	if ( $ENV{"QUERY_STRING"} =~ /\&?pg=(\d+)\&?/ ) {	
		$page = $1;
	}

	if ( $ENV{"QUERY_STRING"} =~ /\&?q=([^&]+)\&?/ ) {	
		$encd_search_str = $1;
		$search_string = $encd_search_str;
		$search_string =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;	
		if ( length($search_string) > 0 ) {
			$query_mode = 1;
		}
	}

	if ( $ENV{"QUERY_STRING"} =~ /\&?per_page=(\d+)\&?/ ) {	

		my $possib_per_page = $1;
			
		if (($possib_per_page % 10) == 0) { 	
			$per_page = $possib_per_page;
		}
		else {
			if ($possib_per_page < 10) {
				$per_page = 10;
			}
			else {
				$per_page = substr("".$possib_per_page, 0, -1) . "0";
			}
		}
		#when the user changes the results per
		#page to more results per page, they should
		#be sent a page down.
		#if they select fewer results per page, they should
		#be sent a page up.
		$session{"per_page"} = $per_page;

	}

	if ( $ENV{"QUERY_STRING"} =~ /\&?sort_order=([01])\&?/ ) {
		$sort_order = $1;
		$session{"creditors_sort_order"} = $sort_order;
	}

	if ( $ENV{"QUERY_STRING"} =~ /\&?sort_by=([0123])\&?/ ) {
		$sort_by = $1;
		$session{"creditors_sort_by"} = $sort_by;
	}

}

use Digest::HMAC_SHA1 qw/hmac_sha1_hex/;

	my $results = "<em>There're no creditors in the database</em>";

	if ($query_mode) {
		$results = "<em>Sorry, your search did not match any creditors in the database</em>";
	}
	my $per_page_guide = "";
	my $page_guide = "";
	my $res_pages = 0;

	my %creditors = ();
	my $num_creditors = 0;

	my $prep_stmt0 = $con->prepare("SELECT creditor_id,creditor_name,description,amount,time,hmac FROM creditors");
	
	if ( $prep_stmt0 ) {
	
		my $rc = $prep_stmt0->execute();

		if ($rc) {

			while ( my @rslts = $prep_stmt0->fetchrow_array() ) {

				my $creditor_id = $rslts[0];
				my $creditor_name = remove_padding($cipher->decrypt( $rslts[1] ));
				my $description = remove_padding($cipher->decrypt( $rslts[2] ));
				my $amount = remove_padding($cipher->decrypt( $rslts[3] ));
				my $o_time = remove_padding($cipher->decrypt( $rslts[4] ));	

				if ($amount =~ /^\d+(?:\.\d{1,2})?$/) {

					my $hmac = uc(hmac_sha1_hex($creditor_name . $description . $amount . $o_time, $key));

					if ( $hmac eq $rslts[5] ) {

						if ($query_mode) {
							unless ( index(lc($creditor_name),lc($search_string)) >= 0 ) {
								next;
							}
						}

						$creditors{$creditor_id} = {"name" => $creditor_name, "description" => $description, "amount" => $amount, "time" => $o_time};
						$num_creditors++;
					}

				}
			}

		}
		else {
			print STDERR "Couldn't execute SELECT FROM creditors: ", $prep_stmt0->errstr, $/;
		}

	}
	else {
		print STDERR "Couldn't prepare SELECT FROM creditors: ", $prep_stmt0->errstr, $/;
	}

	if ($num_creditors > 0) {

		my %sort_by_lookup = (0 => "name", 1 => "description", 2 => "amount", 3 => "time");
		my $sort_key = $sort_by_lookup{$sort_by};

		my @sorted_creditor_ids = ();

		#sort ascending
		if ($sort_order == 0) {
			#amount, time: do numeric sort
			if ($sort_key eq "amount" or $sort_key eq "time") {
				@sorted_creditor_ids = sort { $creditors{$a}->{$sort_key} <=> $creditors{$b}->{$sort_key} } keys %creditors;
			}
			#name,description: do string sort
			else {
				@sorted_creditor_ids = sort { $creditors{$a}->{$sort_key} cmp $creditors{$b}->{$sort_key} } keys %creditors;
			}
		}
		#sort descending
		else {
			#amount, time: do numeric sort
			if ($sort_key eq "amount" or $sort_key eq "time") {
				@sorted_creditor_ids = sort { $creditors{$b}->{$sort_key} <=> $creditors{$a}->{$sort_key} } keys %creditors;
			}
			#name,description: do string sort
			else {
				@sorted_creditor_ids = sort { $creditors{$b}->{$sort_key} cmp $creditors{$a}->{$sort_key} } keys %creditors;
			}
		}

		#cull the recs I don't need

		my $start = $per_page * ($page - 1);
		my $stop = $start + $per_page;

		my @valid_results = ();
		my $num_valid_results = 0;

		for (my $i = $start; $i < $stop and $i < $num_creditors; $i++) {
			push @valid_results, $sorted_creditor_ids[$i];
			$num_valid_results++;
		}

		#generate table
		if ( $num_valid_results > 0 ) {

			my $query_url_bit = "";
			if ($query_mode) {
				$query_url_bit = "q=$encd_search_str&";
			}

			if ( $num_creditors > 10 ) {

				$per_page_guide .= "<p><em>Results per page</em>: <span style='word-spacing: 1em'>";
				for my $row_cnt (10, 20, 50, 100) {
					if ($row_cnt == $per_page) {
						$per_page_guide .= " <span style='font-weight: bold'>$row_cnt</span>";
					}
					else {
						my $re_ordered_page = $page;
						if ($page > 1) {
							my $preceding_results = $per_page * ($page - 1);
							$re_ordered_page = $preceding_results / $row_cnt;
							#if results will overflow into the next
							#page, bump up the page number
							#save that as an integer
							$re_ordered_page++ unless ($re_ordered_page < int($re_ordered_page));
							$re_ordered_page = int($re_ordered_page);
						}

						$per_page_guide .= " <a href='/cgi-bin/creditors.cgi?${query_url_bit}pg=$re_ordered_page&per_page=$row_cnt'>$row_cnt</a>";
					}
				}
				$per_page_guide .= "</span><hr>";

			}

			$res_pages = $num_creditors / $per_page;

			if ($res_pages > 1) {
				if (int($res_pages) < $res_pages) {
					$res_pages = int($res_pages) + 1;
				}
			}

			if ($res_pages > 1) {

				$page_guide .= '<table cellspacing="50%"><tr>';

				if ($page > 1) {
					$page_guide .= "<td><a href='/cgi-bin/creditors.cgi?${query_url_bit}pg=".($page - 1) ."'>Prev</a>";
				}

				if ($page < 10) {
					for (my $i = 1; $i <= $res_pages and $i < 11; $i++) {
						if ($i == $page) {
							$page_guide .= "<td><span style='font-weight: bold'>$i</span>";
						}
						else {
							$page_guide .= "<td><a href='/cgi-bin/creditors.cgi?${query_url_bit}pg=$i'>$i</a>";
						}
					}
				}
				else {
					for (my $i = $page - 4; $i <= $res_pages and $i < ($page + 4); $i++) {
						if ($i == $page) {
							$page_guide .= "<td><span style='font-weight: bold'>$i</span>";
						}
						else {
							$page_guide .= "<td><a href='/cgi-bin/creditors.cgi?${query_url_bit}pg=$i'>$i</a>";
						}
					}
				}

				if ($page < $res_pages) {
					$page_guide .= "<td><a href='/cgi-bin/creditors.cgi?${query_url_bit}pg=".($page + 1)."'>Next</a>";
				}

				$page_guide .= '</table>';

			}

			$results = 
qq!
<TABLE border="1" cellspacing="5%" cellpadding="5%">
<THEAD>
<TH>Creditor
<TH>Description of goods/service
<TH>Amount owed
<TH>Date
</THEAD>
<TBODY>
!;

			for ( my $j = 0; $j < scalar(@valid_results); $j++ ) {

				my @today = localtime($creditors{$valid_results[$j]}->{"time"});
				my $f_time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
				my $f_amount = format_currency($creditors{$valid_results[$j]}->{"amount"});

				my @descr_bts = split/,/,htmlspecialchars($creditors{$valid_results[$j]}->{"description"});

				my $f_description = join("<BR>", @descr_bts);
				my $f_name = htmlspecialchars($creditors{$valid_results[$j]}->{"name"});

				$results .= qq!<TR><TD>$f_name<TD>$f_description<TD>$f_amount<TD>$f_time!;

			}
			$results .= "</TBODY></TABLE>";
		}
	}

	my $escaped_search_str = htmlspecialchars($search_string);

	my %sort_by_lookup = (0 => "Creditor's Name", 1 => "Goods/service", 2 => "Amount owed", 3 => "Date");
	my $sort_by_options = "";

	foreach (0..3) {

		my $selected = "";
		if ($_ == $sort_by) {
			$selected = " selected";
		}

		$sort_by_options .=  qq!<OPTION value="$_" title="$sort_by_lookup{$_}"$selected>$sort_by_lookup{$_}</OPTION>!;

	}

	my %sort_order_lookup = (0 => "Ascending", 1 => "Descending");
	my $sort_order_options = "";

	foreach (0..1) {

		my $selected = "";
		if ($_ == $sort_order) {
			$selected = " selected";
		}

		$sort_order_options .=  qq!<OPTION value="$_" title="$sort_order_lookup{$_}"$selected>$sort_order_lookup{$_}</OPTION>!;	

	}

	$content = 
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::View Creditors</title>

<STYLE type="text/css">

\@media print {

	div.no_header {
		display: none;
	}

}

\@media screen {
	div.noheader {}	
}

</STYLE>
</head>
<body>
<div class="no_header">
$header
</div>
<FORM method="GET" action="/cgi-bin/creditors.cgi">
<TABLE cellspacing="5%" cellpadding="5%">
<TR>
<TD>
<LABEL for="q">Search</LABEL>&nbsp;&nbsp;<INPUT type="text" size="20" name="q" value="$escaped_search_str">
</TD>
<TD>
<LABEL for="sort_by">Sort By</LABEL>&nbsp;&nbsp;

<SELECT name="sort_by">
$sort_by_options
</SELECT>
</TD>

<TD>
<LABEL for="sort_order">Sort Order</LABEL>&nbsp;&nbsp;

<SELECT name="sort_order">
$sort_order_options
</SELECT>

</TD>

<TD>
<INPUT type="submit" name="search" value="Search">
</TD>
</TABLE>
</FORM>
$per_page_guide
<HR>
$results
$page_guide
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
